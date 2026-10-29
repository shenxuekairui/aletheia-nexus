"""Publisher-neutral Chromium PDF viewer recovery primitives."""

import base64
import json
import re
import threading
import time
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from .downloads import CdpDownloadCapture
from .observation import bounded_read

_PDF_VIEWER_EXTENSION_ID = "mhjfbmdgcfjbbpaeojofohoefgiehjai"


class NativeViewerDownloadError(RuntimeError):
    """A visible save action failed, with an optional observed download URL."""

    def __init__(self, reason: str, url: str | None = None):
        super().__init__(reason)
        self.url = url


def is_native_pdf_placeholder(body: bytes) -> bool:
    """Recognize Chromium's replacement document, never by its byte count."""
    if b"%PDF-" in body[:1024] or not body.lstrip().lower().startswith(
        (b"<!doctype html", b"<html")
    ):
        return False

    class PlaceholderParser(HTMLParser):
        found = False

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if (
                tag == "embed"
                and (values.get("type") or "").lower() == "application/pdf"
                and values.get("src") == "about:blank"
                and values.get("internalid")
            ):
                self.found = True

    parser = PlaceholderParser()
    parser.feed(body[:16384].decode("utf-8", errors="replace"))
    return parser.found


_PDF_VIEWER_SAVE_CONTROL = r"""
  const seen = new Set();
  // Edge's built-in Acrobat-style viewer has a local #save outside Chrome's
  // viewer-download-controls. Only this exact built-in extension entry point
  // and its explicit Ctrl+S label establish that local action; arbitrary web
  // pages, cloud controls and generic #save buttons remain ineligible.
  const edgeViewer = location.protocol === 'chrome-extension:'
    && location.hostname === 'mhjfbmdgcfjbbpaeojofohoefgiehjai'
    && location.pathname === '/edge_pdf/index.html';
  function cloudControl(element) {
    let current = element;
    while (current) {
      const identity = `${current.localName || ''} ${current.id || ''}
        ${current.getAttribute?.('title') || ''}
        ${current.getAttribute?.('aria-label') || ''}`.toLowerCase();
      if (/drive|cloud|upload|云|上傳|上传/.test(identity)) return true;
      current = current.parentElement || current.getRootNode?.().host;
    }
    return false;
  }
  function find(root, depth, downloadHost = false) {
    if (!root || depth > 10 || seen.has(root)) return null;
    seen.add(root);
    // Distinct shadow roots legitimately have their own #save. Chrome can put
    // Google Drive's control before the local download control in DOM order.
    for (const host of root.querySelectorAll?.('viewer-download-controls') || []) {
      if (host.shadowRoot && !cloudControl(host)) {
        const local = find(host.shadowRoot, depth + 1, true);
        if (local) return local;
      }
    }
    for (const button of root.querySelectorAll?.('button, cr-icon-button') || []) {
      if (cloudControl(button)) continue;
      const title = (button.getAttribute('title') || button.getAttribute('aria-label') || '').trim();
      if (button.id === 'download'
          || (downloadHost && button.id === 'save')
          || (edgeViewer && button.id === 'save'
              && /^(?:save|保存|儲存)\s*[（(]Ctrl\s*\+\s*S[）)]$/i.test(title))
          || /^(?:download|下载|下載)(?:\s+file|文件)?$/i.test(title)) return button;
    }
    for (const el of root.querySelectorAll?.('*') || []) {
      if (el.shadowRoot && !cloudControl(el)) {
        const found = find(el.shadowRoot, depth + 1,
          el.localName === 'viewer-download-controls');
        if (found) return found;
      }
    }
    return null;
  }
  const button = find(document, 0);
"""

_PDF_VIEWER_SAVE_EXPRESSION = (
    "(() => {"
    + _PDF_VIEWER_SAVE_CONTROL
    + r"""
  if (!button) return {clicked: false};
  button.click();
  return {clicked: true};
})()
"""
)

_PDF_VIEWER_SAVE_READY_EXPRESSION = (
    "(() => {"
    + _PDF_VIEWER_SAVE_CONTROL
    + r"""
  if (!button) return {ready: false};
  const rect = button.getBoundingClientRect();
  return {ready: !button.disabled && !button.hasAttribute('disabled')
    && button.getAttribute('aria-disabled') !== 'true'
    && getComputedStyle(button).visibility !== 'hidden'
    && rect.width > 0 && rect.height > 0};
})()
"""
)

# Chromium records the document URL on the PDF plugin even when its frame
# tree exposes only the extension URL. Read that attribute without fetching.
_PDF_VIEWER_DOCUMENT_EXPRESSION = r"""
(() => {
  const seen = new Set();
  function find(root, depth) {
    if (!root || depth > 10 || seen.has(root)) return null;
    seen.add(root);
    const plugin = root.querySelector?.('embed[original-url]');
    if (plugin) return plugin.getAttribute('original-url');
    for (const el of root.querySelectorAll?.('*') || []) {
      if (el.shadowRoot) {
        const url = find(el.shadowRoot, depth + 1);
        if (url) return url;
      }
    }
    return null;
  }
  return find(document, 0);
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


_PDF_FETCH_SCRIPT = """async ({url, maxBytes, timeoutMs, cache, returnBody, diagnostics}) => {
    const controller = new AbortController();
    let timer;
    let observed = {};
    const failed = (reason, extra = {}) => diagnostics
      ? {ok: false, reason, ...observed, ...extra} : null;
    const read = async () => {
        const response = await fetch(url, {
            cache, credentials: 'include', signal: controller.signal
        });
        const declared = Number(response.headers.get('content-length') || 0);
        observed = {url: response.url || url, status: response.status,
          contentType: response.headers.get('content-type'), declaredBytes: declared};
        if (!response.ok) {
            controller.abort();
            return failed('HTTP_STATUS');
        }
        if (declared > 0 && declared > maxBytes) {
            controller.abort();
            return failed('DECLARED_SIZE_LIMIT');
        }
        if (!response.body) return failed('NO_RESPONSE_BODY');
        const reader = response.body.getReader();
        const chunks = [];
        let size = 0;
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            size += value.byteLength;
            if (size > maxBytes) {
                controller.abort();
                return failed('STREAM_SIZE_LIMIT', {receivedBytes: size});
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
            return failed('NOT_PDF', {receivedBytes: size,
              documentType: new TextDecoder().decode(bytes.slice(0, 64)).trim()
                .match(/^<!doctype html|^<html|^<script/i) ? 'html' : 'other'});
        }
        if (!returnBody) return true;
        let binary = '';
        for (let i = 0; i < bytes.length; i += 0x8000) {
            binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        }
        const result = {url: response.url || url, bodyBase64: btoa(binary)};
        return diagnostics ? {...result, ...observed, ok: true, receivedBytes: size} : result;
    };
    const expired = new Promise(resolve => {
        timer = setTimeout(() => {controller.abort(); resolve(failed('TIMEOUT'));}, timeoutMs);
    });
    try {return await Promise.race([read(), expired]);}
    catch (error) {return failed('REQUEST_FAILED', {errorType: error.name});}
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
            bounded_read(
                page,
                "evaluate",
                _PDF_FETCH_SCRIPT,
                {
                    "url": page_url,
                    "maxBytes": max_bytes,
                    "timeoutMs": max(1, int(timeout * 1000)),
                    "cache": "no-store",
                    "returnBody": False,
                },
                timeout=timeout,
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
            if needs_embed and not bounded_read(
                frame.locator(
                    "embed[type='application/pdf'], object[type='application/pdf']"
                ),
                "count",
                timeout=min(2.0, remaining),
            ):
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            result = bounded_read(
                page,
                "evaluate",
                _PDF_FETCH_SCRIPT,
                {
                    "url": frame_url,
                    "maxBytes": max_bytes,
                    "timeoutMs": max(1, int(remaining * 1000)),
                    "cache": "force-cache",
                    "returnBody": True,
                },
                timeout=remaining,
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


def _target_command(session, target_session, page, method, params, timeout):
    """Read one attached viewer target with a bounded response wait."""
    done = threading.Event()
    response = {}

    def receive(event):
        if event.get("sessionId") != target_session:
            return
        message = json.loads(event["message"])
        if message.get("id") == 7:
            response.update(message)
            done.set()

    session.on("Target.receivedMessageFromTarget", receive)
    try:
        session.send(
            "Target.sendMessageToTarget",
            {
                "sessionId": target_session,
                "message": json.dumps({"id": 7, "method": method, "params": params}),
            },
        )
        deadline = time.monotonic() + max(0, timeout)
        while not done.is_set() and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        return response.get("result", {})
    finally:
        remove = getattr(session, "remove_listener", None)
        if callable(remove):
            remove("Target.receivedMessageFromTarget", receive)


def _viewer_for_document_url(session, page, targets, *, timeout):
    """Resolve generic filenames through the browser's actual frame ownership."""
    expected_url = str(page.url or "").split("#", 1)[0]
    if not expected_url.startswith(("https://", "http://")):
        return None
    deadline = time.monotonic() + max(0, timeout)
    for target in targets:
        if target.get("type") != "webview" or _PDF_VIEWER_EXTENSION_ID not in str(
            target.get("url", "")
        ):
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        attached = None
        try:
            attached = session.send(
                "Target.attachToTarget",
                {
                    "targetId": target["targetId"],
                    "flatten": False,
                },
            )["sessionId"]
            result = _target_command(
                session, attached, page, "Page.getFrameTree", {}, min(1, remaining)
            )
            pending = [result.get("frameTree", {})]
            while pending:
                node = pending.pop()
                frame = node.get("frame", {})
                if str(frame.get("url", "")).split("#", 1)[0] == expected_url:
                    return target
                pending.extend(node.get("childFrames", []))
            remaining = deadline - time.monotonic()
            if remaining > 0:
                result = _target_command(
                    session,
                    attached,
                    page,
                    "Runtime.evaluate",
                    {
                        "expression": _PDF_VIEWER_DOCUMENT_EXPRESSION,
                        "returnByValue": True,
                    },
                    min(1, remaining),
                )
                document_url = result.get("result", {}).get("value")
                if (
                    isinstance(document_url, str)
                    and document_url.split("#", 1)[0] == expected_url
                ):
                    return target
        except Exception:
            continue
        finally:
            if attached is not None:
                try:
                    session.send("Target.detachFromTarget", {"sessionId": attached})
                except Exception:
                    pass
    return None


def _owned_pdf_viewer_targets(targets, *, owner_target_id, owner_frame_ids):
    """Restrict native save controls to descendants of one caller-owned page.

    Modern Chromium exposes its PDF extension as an iframe target; older builds
    can expose a webview. A matching title/URL alone cannot establish ownership
    when a user has another copy of that same PDF open.
    """
    descendants = {owner_target_id}
    changed = True
    while changed:
        changed = False
        for target in targets:
            target_id = target.get("targetId")
            if not target_id or target_id in descendants:
                continue
            if target.get("parentId") in descendants or (
                not target.get("parentId")
                and target.get("parentFrameId") in owner_frame_ids
            ):
                descendants.add(target_id)
                changed = True
    result = []
    for target in targets:
        parsed = urlsplit(str(target.get("url") or ""))
        if (
            target.get("targetId") in descendants - {owner_target_id}
            and target.get("type") in {"webview", "iframe"}
            and parsed.scheme == "chrome-extension"
            and parsed.hostname == _PDF_VIEWER_EXTENSION_ID
        ):
            result.append(target)
    return result


def _frame_tree_ids(tree):
    pending, found = [tree.get("frameTree", {})], set()
    while pending:
        node = pending.pop()
        frame_id = node.get("frame", {}).get("id")
        if isinstance(frame_id, str) and frame_id:
            found.add(frame_id)
        pending.extend(node.get("childFrames", []))
    return found


def trigger_pdf_viewer_save(
    context,
    page,
    *,
    doi: str,
    output_dir: str | Path,
    expected_title: str | None,
    timeout: float,
    max_bytes: int,
    owned_page_only: bool = False,
    native_capture=None,
    owned_frame_ids=None,
    download_wait=None,
    diagnostics: list[str] | None = None,
) -> tuple[Path, Path] | None:
    """Save the current Chromium PDF webview through its native save control."""

    def unavailable(reason):
        if diagnostics is not None and reason not in diagnostics:
            diagnostics.append(reason)
        return None

    if owned_page_only and (owned_frame_ids is None or not callable(download_wait)):
        return None
    # Public Playwright contexts support exact page/target ownership. Keep the
    # older heuristic only for adapters that cannot expose this API; never fall
    # back to another tab when a real context proves no unique owned viewer.
    scoped = owned_page_only or callable(getattr(context, "new_cdp_session", None))
    if owned_frame_ids is None:
        owned_frame_ids = set()
    owns_capture = native_capture is None
    capture = (
        CdpDownloadCapture(context, output_dir) if owns_capture else native_capture
    )
    session = capture.session
    staging_dir = capture.staging_dir
    if session is None or staging_dir is None:
        return unavailable("NativePdfViewerCaptureUnavailable")

    target_session: str | None = None
    receive_target = None
    keep_staging = False
    operation_deadline = time.monotonic() + timeout if scoped else None
    try:
        if scoped:
            owner = context.new_cdp_session(page)
            try:
                info = owner.send("Target.getTargetInfo").get("targetInfo", {})
                owned_frame_ids.update(_frame_tree_ids(owner.send("Page.getFrameTree")))
            finally:
                owner.detach()
            ready_deadline = min(
                operation_deadline,
                time.monotonic()
                + (2.0 if owned_page_only or is_pdf_document_url(str(page.url)) else 0),
            )
            while True:
                targets = session.send("Target.getTargets").get("targetInfos", [])
                candidates = _owned_pdf_viewer_targets(
                    targets,
                    owner_target_id=info.get("targetId"),
                    owner_frame_ids=owned_frame_ids,
                )
                if candidates or time.monotonic() >= ready_deadline:
                    break
                page.wait_for_timeout(100)
            if not info.get("targetId") or len(candidates) != 1:
                return unavailable(
                    "NativePdfViewerTargetAmbiguous"
                    if len(candidates) > 1
                    else "NativePdfViewerOwnedTargetNotFound"
                )
            target = candidates[0]
        else:
            try:
                page_title = bounded_read(page, "title", timeout=min(2.0, timeout))
            except Exception:
                # Recovery may be running precisely because the page DOM cannot
                # be read. Matching still requires article title/DOI/URL below.
                page_title = ""
            targets = session.send("Target.getTargets").get("targetInfos", [])
            target = select_pdf_viewer_target(
                targets,
                doi=doi,
                expected_title=expected_title,
                page_title=page_title,
                page_url=str(page.url or ""),
            )
        if target is None and not scoped:
            # Untitled PDFs can expose only "main.pdf" in the viewer and no
            # readable top-level title. Never guess from that common filename.
            target = _viewer_for_document_url(
                session, page, targets, timeout=min(3.0, timeout)
            )
        if target is None:
            return unavailable("NativePdfViewerTargetNotFound")

        target_session = session.send(
            "Target.attachToTarget",
            {"targetId": target["targetId"], "flatten": False},
        )["sessionId"]

        if scoped:
            tree = _target_command(
                session,
                target_session,
                page,
                "Page.getFrameTree",
                {},
                min(1.0, max(0.0, operation_deadline - time.monotonic())),
            )
            owned_frame_ids.update(_frame_tree_ids(tree))
            ready_deadline = min(operation_deadline, time.monotonic() + 3.0)
            while True:
                observed = _target_command(
                    session,
                    target_session,
                    page,
                    "Runtime.evaluate",
                    {
                        "expression": _PDF_VIEWER_SAVE_READY_EXPRESSION,
                        "returnByValue": True,
                    },
                    min(1.0, max(0.0, ready_deadline - time.monotonic())),
                )
                ready = observed.get("result", {}).get("value", {}).get("ready", False)
                if ready or time.monotonic() >= ready_deadline:
                    break
                page.wait_for_timeout(100)
            if not ready:
                return unavailable("NativePdfViewerLocalSaveControlUnavailable")

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
                            **({"userGesture": True} if scoped else {}),
                        },
                    }
                ),
            },
        )

        deadline = operation_deadline if scoped else time.monotonic() + timeout
        while not runtime_done.is_set() and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        click_result = (
            runtime_result.get("result", {}).get("result", {}).get("value", {})
        )
        if not isinstance(click_result, dict) or not click_result.get("clicked"):
            return unavailable("NativePdfViewerLocalSaveNotAcknowledged")
        remaining = max(0.0, deadline - time.monotonic())
        captured = (
            download_wait(page, remaining)
            if owned_page_only
            else capture.wait(
                page,
                remaining,
                wait_for_start=True,
                **({"expected_frame_ids": owned_frame_ids} if scoped else {}),
            )
        )
        if captured is None:
            if owned_page_only:
                raise NativeViewerDownloadError(
                    "OwnedNativeDownloadIncomplete", str(page.url)
                )
            if scoped:
                raise NativeViewerDownloadError(
                    "NativePdfViewerOwnedDownloadIncomplete", str(page.url)
                )
            if capture.cancelled_url:
                raise NativeViewerDownloadError(
                    "NativeDownloadCanceled", capture.cancelled_url
                )
            raise NativeViewerDownloadError(
                "NativeDownloadIncomplete"
                if capture.started
                else "NativeDownloadStartTimeout"
            )
        saved, _ = captured
        if saved.stat().st_size > max_bytes:
            if owned_page_only:
                raise NativeViewerDownloadError(
                    "NativeDownloadSizeLimit", str(page.url)
                )
            return unavailable("NativePdfViewerDownloadSizeLimit")
        with saved.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return unavailable("NativePdfViewerNonPdfDelivery")
        keep_staging = True
        return saved, staging_dir
    except NativeViewerDownloadError:
        raise
    except Exception as exc:
        if owned_page_only:
            raise
        return unavailable(f"NativePdfViewerSaveError:{type(exc).__name__}")
    finally:
        remove = getattr(session, "remove_listener", None)
        if receive_target is not None and callable(remove):
            remove("Target.receivedMessageFromTarget", receive_target)
        if target_session is not None:
            try:
                session.send(
                    "Target.detachFromTarget",
                    {"sessionId": target_session},
                )
            except Exception:
                pass
        if owns_capture:
            unclaimed = getattr(capture, "has_unclaimed_downloads", None)
            preserve_unclaimed = (
                scoped and callable(unclaimed) and unclaimed(owned_frame_ids)
            )
            capture.close(remove_files=not keep_staging and not preserve_unclaimed)
