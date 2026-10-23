"""Opt-in, synchronous acquisition diagnostics; never changes acquisition policy.

Installed only by scripts/profile_acquisition.py. No URLs, arguments, page text,
exception messages, credentials, or PDF bodies are serialized. Inclusive spans
form a tree; exclusive times subtract direct children, not all descendants.
"""

from __future__ import annotations

import importlib
import json
import sys
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from weakref import WeakKeyDictionary


class AcquisitionTimer:
    def __init__(self, path, *, clock=time.perf_counter):
        self.path = Path(path)
        self.stream = self.path.open("x", encoding="utf-8")
        self.clock = clock
        self.origin = clock()
        self.local = threading.local()
        self.lock = threading.RLock()
        self.spans = []
        self.patches = []
        self.write_seconds = 0.0
        self.write_failed = False
        self.stop = threading.Event()
        self.worker = None
        self.emit({"event": "run", "schema": "an-timing/v1"})

    def stack(self):
        # Playwright dispatches callbacks on separate greenlets in the SAME
        # thread. A thread-local stack alone creates crossing/non-LIFO spans.
        try:
            from greenlet import getcurrent

            lane = getcurrent()
        except ImportError:
            lane = threading.current_thread()
        lanes = getattr(self.local, "lanes", None)
        if lanes is None:
            lanes = self.local.lanes = WeakKeyDictionary()
        return lanes.setdefault(lane, [])

    def emit(self, event):
        with self.lock:
            before = time.perf_counter()
            try:
                self.stream.write(
                    json.dumps(
                        {
                            "utc": datetime.now(timezone.utc).isoformat(),
                            **event,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                self.stream.flush()
            except OSError:
                # Diagnostics must not turn a successful acquisition into failure.
                self.write_failed = True
            self.write_seconds += time.perf_counter() - before

    @contextmanager
    def span(self, name, category, *, paper=None, site=None):
        stack = self.stack()
        with self.lock:
            parent = stack[-1] if stack else None
            row = {
                "id": len(self.spans) + 1,
                "parent": parent["id"] if parent else None,
                "name": name,
                "category": category,
                "start": self.clock() - self.origin,
                "paper": paper or (parent["paper"] if parent else None),
                "site": site,
            }
            self.spans.append(row)
            stack.append(row)
        self.emit({"event": "start", **row})
        try:
            yield row
        except BaseException as exc:
            row["error_type"] = type(exc).__name__
            raise
        finally:
            with self.lock:
                row["end"] = self.clock() - self.origin
                row["seconds"] = row["end"] - row["start"]
                stack.pop()
            self.emit({"event": "end", **row})

    def notice(self, kind):
        # A window is notification -> resolver return, not pure human time.
        stack = self.stack()
        owner = next(
            (s for s in reversed(stack) if s["category"] == "access_gate"), None
        )
        now = self.clock() - self.origin
        if owner is not None:
            owner.setdefault("interaction_start", now)
        self.emit(
            {
                "event": "interaction_notice",
                "kind": kind,
                "at": now,
                "owner": owner["id"] if owner else None,
            }
        )

    def wrap(self, function, category, *, name=None, paper=False):
        label = name or function.__qualname__

        @wraps(function)
        def measured(*args, **kwargs):
            identifier = None
            if paper:
                request = args[0] if args else kwargs.get("doi")
                identifier = getattr(request, "doi", None)
                if identifier is None and isinstance(request, str):
                    identifier = request if request.startswith("10.") else None
                identifier = identifier or getattr(
                    request, "key", "citation-without-doi"
                )
            caller = sys._getframe(1)
            module = caller.f_globals.get("__name__", "")
            site = (
                f"{module}:{caller.f_lineno}:{caller.f_code.co_name}"
                if module.startswith("aletheia_nexus.")
                else None
            )
            del caller
            with self.span(label, category, paper=identifier, site=site) as row:
                result = function(*args, **kwargs)
                status = getattr(result, "status", None)
                if status is not None and isinstance(
                    getattr(status, "value", None), str
                ):
                    row["status"] = status.value
                if (
                    isinstance(result, tuple)
                    and len(result) == 2
                    and isinstance(result[1], bytes)
                ):
                    row["bytes"] = len(result[1])
                elif isinstance(result, bytes):
                    row["bytes"] = len(result)
                return result

        return measured

    def patch(self, owner, attribute, replacement):
        old = getattr(owner, attribute)
        self.patches.append((owner, attribute, old, replacement))
        setattr(owner, attribute, replacement)

    def heartbeat(self):
        with self.lock:
            now = self.clock() - self.origin
            pending = [s for s in self.spans if "end" not in s]
            parents = {s["parent"] for s in pending}
            leaves = [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "paper": s["paper"],
                    "site": s["site"],
                    "elapsed": now - s["start"],
                }
                for s in pending
                if s["id"] not in parents
            ]
        self.emit({"event": "heartbeat", "pending": leaves})

    def start_heartbeat(self, interval=10):
        def run():
            while not self.stop.wait(interval):
                self.heartbeat()

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def summary(self):
        finished = [s for s in self.spans if "end" in s]
        children = defaultdict(list)
        for row in finished:
            children[row["parent"]].append(row)
        papers = []
        for root in finished:
            if root["category"] != "paper":
                continue
            rows = []

            def visit(row):
                rows.append(row)
                for child in children[row["id"]]:
                    visit(child)

            visit(root)
            categories = defaultdict(float)
            details = []
            errors = []
            for row in rows:
                direct = sorted(children[row["id"]], key=lambda c: c["start"])
                boundary = row["start"]
                for child in direct:
                    if (
                        child["start"] < boundary - 1e-8
                        or child["end"] > row["end"] + 1e-8
                    ):
                        errors.append(
                            {
                                "parent": row["id"],
                                "child": child["id"],
                                "reason": "overlap_or_outside_parent",
                            }
                        )
                    boundary = child["end"]
                own = row["seconds"] - sum(c["seconds"] for c in children[row["id"]])
                categories[row["category"]] += own
                details.append({**row, "exclusive_seconds": own})
            windows = sorted(
                (r["interaction_start"], r["end"])
                for r in rows
                if "interaction_start" in r
            )
            merged = []
            for start, end in windows:
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(end, merged[-1][1])
                else:
                    merged.append([start, end])
            interaction = sum(end - start for start, end in merged)
            papers.append(
                {
                    "paper": root["paper"],
                    "span_id": root["id"],
                    "status": root.get("status"),
                    "seconds": root["seconds"],
                    "exclusive_categories": dict(categories),
                    "accounting_delta": root["seconds"] - sum(categories.values()),
                    "timing_valid": not errors,
                    "timing_errors": errors,
                    "interaction_window_seconds": interaction,
                    "outside_interaction_seconds": root["seconds"] - interaction,
                    "spans": details,
                }
            )
        return {
            "schema": "an-timing-summary/v1",
            "papers": papers,
            "trace_write_seconds": self.write_seconds,
            "trace_write_failed": self.write_failed,
            "incomplete_spans": [s for s in self.spans if "end" not in s],
            "notes": [
                "Exclusive categories sum to each paper duration; inclusive spans overlap.",
                "Interaction windows overlap categories; never add them to those totals.",
                "Interaction includes human input, site response and clearance polling.",
                "PDF read spans include cache/transport/serialization; not pure network time.",
                "Concurrent discovery work is covered by its parent wall time, not CPU time.",
                "Browser callback work is included in the enclosing sync call, not subtracted twice.",
                "Trace write time is measured overhead, not all instrumentation overhead.",
            ],
        }

    def close(self):
        self.stop.set()
        if self.worker is not None:
            self.worker.join(timeout=2)
        for owner, attribute, old, replacement in reversed(self.patches):
            if getattr(owner, attribute) is replacement:
                setattr(owner, attribute, old)
        self.stream.close()


# All module aliases are replaced by identity, so imported call sites are covered.
_FUNCTIONS = {
    "access.batch": {"_acquire_item": "paper"},
    "access.service": {"acquire_full_text_maximized": "acquisition"},
    "fulltext.orchestration.service": {"acquire_full_text": "public_routes"},
    "discovery.service": {"discover_full_text": "discovery"},
    "metadata.resolver": {"get_metadata": "metadata"},
    "fulltext.service": {"acquire_direct_pdf": "direct_pdf"},
    "fulltext.transport": {"retrieve_to_temp": "http_pdf_to_temp"},
    "fulltext.validation": {"inspect_pdf": "pdf_parse"},
    "fulltext.identity": {"validate_paper_identity": "identity_validation"},
    "fulltext.storage": {
        "promote_resource": "file_promote",
        "write_json_sidecar": "sidecar_write",
    },
    "access.artifact": {
        "finalize_access_resource": "finalize",
        "finalize_browser_resource": "finalize",
    },
    "access.browser_route": {
        "_attempt_browser_route": "browser_route",
        "_report_for_page": "state_check",
        "_resolve_page_challenge": "access_gate",
        "_resolve_external_auth_page": "access_gate",
        "_wait_until_challenge_changes": "gate_polling",
        "_run_institution_handoff": "institution",
        "_click_semantic_pdf_control": "pdf_control",
        "_dismiss_blocking_modal": "modal",
        "_observe_pdf_popups": "popup",
        "_resource_from_bytes": "temp_write",
        "_request_pdf_candidate": "pdf_request",
        "_browser_response_to_file_attempt": "response_pdf",
        "_download_to_file_attempt": "download_pdf",
    },
    "access.browser_engine.viewer": {
        "trigger_embedded_pdf_frame_fetch": "viewer_pdf_read",
        "trigger_pdf_viewer_same_origin_fetch": "viewer_pdf_read",
        "trigger_pdf_viewer_save": "viewer_save",
    },
    "access.browser_engine.downloads": {"save_browser_download": "download_save"},
    "access.cnki_provider": {
        "_metadata_for_query": "metadata",
        "_select_search_field": "search_field",
        "_ranked_results": "search_results",
        "_detail_identity": "detail_identity",
        "_capture_download": "download_capture",
        "_finalize_cnki_download": "finalize",
        "_recover_pdf_request": "pdf_recovery",
    },
}


def install(timer):
    """Install in a dedicated sequential CLI process; restore with timer.close()."""
    modules = {
        suffix: importlib.import_module("aletheia_nexus.acquire." + suffix)
        for suffix in _FUNCTIONS
    }
    cli = importlib.import_module("aletheia_nexus.cli")
    for suffix, entries in _FUNCTIONS.items():
        for name, category in entries.items():
            original = getattr(modules[suffix], name)
            replacement = timer.wrap(
                original, category, name=f"{suffix}.{name}", paper=category == "paper"
            )
            for module_name, module in list(sys.modules.items()):
                if module is None or not module_name.startswith("aletheia_nexus"):
                    continue
                for alias, value in list(vars(module).items()):
                    if value is original:
                        timer.patch(module, alias, replacement)
    runtime = importlib.import_module("aletheia_nexus.acquire.access.cnki_runtime")
    for owner, attribute, category in (
        (modules["access.cnki_provider"].CNKIProvider, "fetch", "cnki_route"),
        (runtime.CNKIGate, "check", "access_gate"),
        (runtime.CNKIGate, "wait", "cnki_stage_wait"),
        (runtime.CNKIGate, "wait_ready", "cnki_ready"),
    ):
        timer.patch(owner, attribute, timer.wrap(getattr(owner, attribute), category))
    original_notice = cli._interaction_notice

    @wraps(original_notice)
    def notice(challenge, url):
        timer.notice(challenge.kind.value)
        return original_notice(challenge, url)

    timer.patch(cli, "_interaction_notice", notice)

    from playwright._impl._sync_base import SyncBase

    original_sync = SyncBase._sync

    @wraps(original_sync)
    def measured_sync(self, coro):
        stack = timer.stack()
        if not stack:
            return original_sync(self, coro)
        code = getattr(coro, "cr_code", None)
        name = getattr(code, "co_qualname", "browser_call")
        method = name.rsplit(".", 1)[-1]
        category = {
            "goto": "navigation",
            "reload": "navigation",
            "wait_for_load_state": "load_wait",
            "click": "click",
            "fill": "fill",
            "wait_for_timeout": "explicit_wait",
            "body": "response_body",
            "save_as": "download_save",
            "get": "browser_http",
            "evaluate": "browser_evaluate",
        }.get(method, "browser_observation")
        frame = sys._getframe(1)
        site = None
        while frame is not None:
            module = frame.f_globals.get("__name__", "")
            if module.startswith("aletheia_nexus.") and module != __name__:
                site = f"{module}:{frame.f_lineno}:{frame.f_code.co_name}"
                break
            frame = frame.f_back
        del frame
        with timer.span(name, category, site=site) as row:
            result = original_sync(self, coro)
            if isinstance(result, bytes):
                row["bytes"] = len(result)
            return result

    timer.patch(SyncBase, "_sync", measured_sync)
