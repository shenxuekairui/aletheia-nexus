"""Publisher-neutral Chromium PDF viewer recovery primitives."""

import base64
import json
import re
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit

from .downloads import CdpDownloadCapture

_PDF_VIEWER_EXTENSION_ID = "mhjfbmdgcfjbbpaeojofohoefgiehjai"
_PDF_VIEWER_SAVE_EXPRESSION = r"""
(() => {
  const seen = new Set();
  function find(root, depth) {
    if (!root || depth > 10 || seen.has(root)) return null;
    seen.add(root);
    const direct = root.querySelector?.(
      '#save, button[title*="Save"], button[title*="保存"]'
    );
    if (direct) return direct;
    for (const el of root.querySelectorAll?.('*') || []) {
      if (el.shadowRoot) {
        const found = find(el.shadowRoot, depth + 1);
        if (found) return found;
      }
    }
    return null;
  }
  const button = find(document, 0);
  if (!button) return {clicked: false};
  button.click();
  return {clicked: true};
})()
"""


def is_pdf_document_url(url: str) -> bool:
    """Recognize publisher PDF routes as well as literal PDF filenames."""
    try:
        path = urlsplit(url).path.casefold()
        return path.endswith((".pdf", "/pdf")) or any(
            marker in path
            for marker in ("/doi/pdf/", "/doi/epdf/", "/pdfdirect/", "/articlepdf/")
        )
    except ValueError:
        return False


_PDF_FETCH_SCRIPT = """async ({url, maxBytes, timeoutMs, cache, returnBody}) => {
    const controller = new AbortController();
    let timer;
    const read = async () => {
        const response = await fetch(url, {
            cache, credentials: 'include', signal: controller.signal
        });
        const declared = Number(response.headers.get('content-length') || 0);
        if (!response.ok || (declared > 0 && declared > maxBytes)) {
            controller.abort();
            return null;
        }
        if (!response.body) return null;
        const reader = response.body.getReader();
        const chunks = [];
        let size = 0;
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            size += value.byteLength;
            if (size > maxBytes) {
                controller.abort();
                return null;
            }
            chunks.push(value);
        }
        const bytes = new Uint8Array(size);
        let offset = 0;
        for (const chunk of chunks) {
            bytes.set(chunk, offset);
            offset += chunk.byteLength;
        }
        if (!(bytes.length >= 5 && bytes[0] === 0x25 && bytes[1] === 0x50
            && bytes[2] === 0x44 && bytes[3] === 0x46 && bytes[4] === 0x2d)) {
            return null;
        }
        if (!returnBody) return true;
        let binary = '';
        for (let i = 0; i < bytes.length; i += 0x8000) {
            binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        }
        return {url: response.url || url, bodyBase64: btoa(binary)};
    };
    const expired = new Promise(resolve => {
        timer = setTimeout(() => {controller.abort(); resolve(null);}, timeoutMs);
    });
    try {return await Promise.race([read(), expired]);}
    catch (_) {return null;}
    finally {clearTimeout(timer); controller.abort();}
}"""


def trigger_pdf_viewer_same_origin_fetch(
    page, *, max_bytes: int, validate_url, timeout: float = 20.0
) -> bool:
    """Expose plugin-held PDF bytes without unbounded fetch/body reads."""
    try:
        page_url = validate_url(str(page.url or ""))
        if not is_pdf_document_url(page_url):
            return False
        return bool(
            page.evaluate(
                _PDF_FETCH_SCRIPT,
                {
                    "url": page_url,
                    "maxBytes": max_bytes,
                    "timeoutMs": max(1, int(timeout * 1000)),
                    "cache": "no-store",
                    "returnBody": False,
                },
            )
        )
    except Exception:
        return False


def trigger_embedded_pdf_frame_fetch(
    page, *, max_bytes: int, validate_url, timeout: float = 20.0
) -> tuple[str, bytes] | None:
    """Read same-origin PDF frames within one shared time/size budget."""
    try:
        page_url = validate_url(str(page.url or ""))
        page_parts = urlsplit(page_url)
    except Exception:
        return None
    deadline = time.monotonic() + timeout
    candidates = []
    for index, frame in enumerate(getattr(page, "frames", ()) or ()):
        if frame is page:
            continue
        try:
            frame_url = str(frame.url or "")
            frame_parts = urlsplit(frame_url)
            if (frame_parts.scheme, frame_parts.hostname, frame_parts.port) != (
                page_parts.scheme,
                page_parts.hostname,
                page_parts.port,
            ):
                continue
            candidates.append(
                (not is_pdf_document_url(frame_url), index, frame, frame_url)
            )
        except Exception:
            continue
    for needs_embed, _, frame, frame_url in sorted(candidates)[:12]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            frame_url = validate_url(frame_url)
            if (
                needs_embed
                and not frame.locator(
                    "embed[type='application/pdf'], object[type='application/pdf']"
                ).count()
            ):
                continue
            result = page.evaluate(
                _PDF_FETCH_SCRIPT,
                {
                    "url": frame_url,
                    "maxBytes": max_bytes,
                    "timeoutMs": max(1, int(remaining * 1000)),
                    "cache": "force-cache",
                    "returnBody": True,
                },
            )
            if not isinstance(result, dict):
                continue
            result_url = validate_url(str(result.get("url") or ""))
            body = base64.b64decode(str(result.get("bodyBase64") or ""), validate=True)
            if len(body) <= max_bytes and body.startswith(b"%PDF-"):
                return result_url, body
        except Exception:
            continue
    return None


def _normalized_viewer_title(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split())


def _compact_viewer_identifier(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def select_pdf_viewer_target(
    targets: list[dict[str, object]],
    *,
    doi: str,
    expected_title: str | None,
    page_title: str | None,
    page_url: str,
) -> dict[str, object] | None:
    """Select the Chromium PDF webview belonging to the current article."""

    expected = _normalized_viewer_title(expected_title)
    observed_page = _normalized_viewer_title(page_title)
    doi_token = _compact_viewer_identifier(doi.rsplit("/", 1)[-1])
    page_filename = urlsplit(page_url).path.rsplit("/", 1)[-1]
    page_file_token = _compact_viewer_identifier(page_filename.removesuffix(".pdf"))
    ranked: list[tuple[float, dict[str, object]]] = []
    for target in targets:
        target_url = str(target.get("url") or "")
        if (
            target.get("type") != "webview"
            or _PDF_VIEWER_EXTENSION_ID not in target_url
        ):
            continue
        title = _normalized_viewer_title(str(target.get("title") or ""))
        if not title:
            continue
        compact_title = _compact_viewer_identifier(title)
        expected_score = (
            SequenceMatcher(None, expected, title).ratio() if expected else 0
        )
        page_score = (
            SequenceMatcher(None, title, observed_page).ratio() if observed_page else 0
        )
        score = max(expected_score, page_score)
        if expected and (title in expected or expected in title):
            score += 1
        if any(
            len(token) >= 6 and token in compact_title
            for token in (doi_token, page_file_token)
        ):
            score += 2
        ranked.append((score, target))
    if not ranked:
        return None
    score, winner = max(ranked, key=lambda item: item[0])
    return winner if score >= 0.72 else None


def trigger_pdf_viewer_save(
    context,
    page,
    *,
    doi: str,
    output_dir: str | Path,
    expected_title: str | None,
    timeout: float,
    max_bytes: int,
) -> tuple[Path, Path] | None:
    """Save the current Chromium PDF webview through its native save control."""

    capture = CdpDownloadCapture(context, output_dir)
    session = capture.session
    staging_dir = capture.staging_dir
    if session is None or staging_dir is None:
        return None

    target_session: str | None = None
    keep_staging = False
    try:
        page_title = page.title()
        target = select_pdf_viewer_target(
            session.send("Target.getTargets").get("targetInfos", []),
            doi=doi,
            expected_title=expected_title,
            page_title=page_title,
            page_url=str(page.url or ""),
        )
        if target is None:
            return None

        target_session = session.send(
            "Target.attachToTarget",
            {"targetId": target["targetId"], "flatten": False},
        )["sessionId"]

        runtime_done = threading.Event()
        runtime_result: dict[str, object] = {}

        def receive_target(event) -> None:
            if event.get("sessionId") != target_session:
                return
            message = json.loads(event["message"])
            if message.get("id") == 1:
                runtime_result.update(message)
                runtime_done.set()

        session.on("Target.receivedMessageFromTarget", receive_target)
        session.send(
            "Target.sendMessageToTarget",
            {
                "sessionId": target_session,
                "message": json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": _PDF_VIEWER_SAVE_EXPRESSION,
                            "returnByValue": True,
                        },
                    }
                ),
            },
        )

        deadline = time.monotonic() + timeout
        while not runtime_done.is_set() and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        click_result = (
            runtime_result.get("result", {}).get("result", {}).get("value", {})
        )
        if not isinstance(click_result, dict) or not click_result.get("clicked"):
            return None
        captured = capture.wait(page, max(0.0, deadline - time.monotonic()))
        if captured is None:
            return None
        saved, _ = captured
        if saved.stat().st_size > max_bytes:
            return None
        with saved.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return None
        keep_staging = True
        return saved, staging_dir
    except Exception:
        return None
    finally:
        if target_session is not None:
            try:
                session.send(
                    "Target.detachFromTarget",
                    {"sessionId": target_session},
                )
            except Exception:
                pass
        capture.close(remove_files=not keep_staging)
