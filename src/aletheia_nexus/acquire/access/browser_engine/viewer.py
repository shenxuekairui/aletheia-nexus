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


def trigger_pdf_viewer_same_origin_fetch(page, *, max_bytes: int, validate_url) -> bool:
    """Expose Chromium's plugin-held PDF stream as one capturable response."""

    try:
        deadline = time.monotonic() + 5.0
        while True:
            page_url = validate_url(str(page.url or ""))
            if urlsplit(page_url).path.lower().endswith(".pdf"):
                break
            if time.monotonic() >= deadline:
                return False
            page.wait_for_timeout(250)
        result = page.evaluate(
            """async (maxBytes) => {
                const response = await fetch(location.href, {
                    cache: 'no-store',
                    credentials: 'include'
                });
                const declared = Number(response.headers.get('content-length') || 0);
                if (!response.ok || (declared > 0 && declared > maxBytes)) {
                    if (response.body) await response.body.cancel();
                    return false;
                }
                const buffer = await response.arrayBuffer();
                if (buffer.byteLength > maxBytes) return false;
                const head = new Uint8Array(buffer.slice(0, 5));
                return head.length === 5
                    && head[0] === 0x25
                    && head[1] === 0x50
                    && head[2] === 0x44
                    && head[3] === 0x46
                    && head[4] === 0x2d;
            }""",
            max_bytes,
        )
        return bool(result)
    except Exception:
        return False


def trigger_embedded_pdf_frame_fetch(
    page, *, max_bytes: int, validate_url
) -> tuple[str, bytes] | None:
    """Expose a same-origin PDF loaded inside a publisher viewer iframe.

    Chromium's built-in PDF viewer can replace the iframe's JavaScript world with
    an extension document. Run the cache-only fetch from the publisher's top-level
    page instead, where cookies and the same-origin relationship remain intact.
    """

    script = """async ({url, maxBytes}) => {
        const response = await fetch(url, {
            cache: 'force-cache',
            credentials: 'include'
        });
        const declared = Number(response.headers.get('content-length') || 0);
        if (!response.ok || (declared > 0 && declared > maxBytes)) {
            if (response.body) await response.body.cancel();
            return false;
        }
        const buffer = await response.arrayBuffer();
        if (buffer.byteLength > maxBytes) return false;
        const bytes = new Uint8Array(buffer);
        if (!(bytes.length >= 5
            && bytes[0] === 0x25
            && bytes[1] === 0x50
            && bytes[2] === 0x44
            && bytes[3] === 0x46
            && bytes[4] === 0x2d)) return false;
        let binary = '';
        const chunkSize = 0x8000;
        for (let offset = 0; offset < bytes.length; offset += chunkSize) {
            binary += String.fromCharCode(
                ...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length))
            );
        }
        return {url: response.url || url, bodyBase64: btoa(binary)};
    }"""
    try:
        page_url = validate_url(str(page.url or ""))
        page_parts = urlsplit(page_url)
    except Exception:
        return False
    for frame in list(getattr(page, "frames", ()) or ())[:12]:
        if frame is page:
            continue
        try:
            frame_url = validate_url(str(frame.url or ""))
            path = urlsplit(frame_url).path.lower()
            has_pdf_embed = bool(
                frame.locator(
                    "embed[type='application/pdf'], object[type='application/pdf']"
                ).count()
            )
            if not (
                path.endswith(".pdf")
                or "/pdfdirect/" in path
                or "/doi/pdf/" in path
                or has_pdf_embed
            ):
                continue
            frame_parts = urlsplit(frame_url)
            if (
                frame_parts.scheme,
                frame_parts.hostname,
                frame_parts.port,
            ) != (page_parts.scheme, page_parts.hostname, page_parts.port):
                continue
            result = page.evaluate(
                script,
                {"url": frame_url, "maxBytes": max_bytes},
            )
            if not isinstance(result, dict):
                continue
            result_url = validate_url(str(result.get("url") or ""))
            body = base64.b64decode(str(result.get("bodyBase64") or ""), validate=True)
            if len(body) > max_bytes or not body.startswith(b"%PDF-"):
                continue
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
