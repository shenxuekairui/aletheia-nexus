"""Bounded, read-only diagnostics for an unsuccessful local CDP attachment.

The browser remains owned by its user. This module never attaches to a target,
navigates a page, retries a connection, or records target URLs/titles/IDs. The
HTTP endpoints are Chromium's local control endpoints, not publisher requests.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from .viewer import is_pdf_document_url

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_MAX_JSON_BYTES = 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def inspect_local_endpoint(endpoint: str) -> dict:
    """Return only aggregate target information, with at most two local reads.

    Do not use system proxies, follow redirects, retain raw CDP payloads, or
    inspect authentication state. A failed probe is a diagnostic, never a
    reason to restart a browser or declare that its pages have stopped.
    """
    result = {"endpoint_reachable": False}
    try:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https", "ws", "wss"}
            or parsed.hostname not in _LOOPBACK
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.scheme in {"http", "https"} and parsed.path not in {"", "/"})
            or (
                parsed.scheme in {"ws", "wss"}
                and not parsed.path.startswith("/devtools/browser/")
            )
        ):
            return {"endpoint_probe": "UNSUPPORTED_ENDPOINT_SHAPE"}
        scheme = "https" if parsed.scheme in {"https", "wss"} else "http"
        opener = build_opener(ProxyHandler({}), _NoRedirect())

        def read(path):
            url = urlunsplit((scheme, parsed.netloc, path, "", ""))
            with opener.open(url, timeout=0.5) as response:
                body = response.read(_MAX_JSON_BYTES + 1)
            if len(body) > _MAX_JSON_BYTES:
                raise ValueError("Local control response exceeds diagnostic limit")
            return json.loads(body)

        version = read("/json/version")
        websocket = urlsplit(version["webSocketDebuggerUrl"])
        endpoint_port = parsed.port or (443 if scheme == "https" else 80)
        websocket_port = websocket.port or (443 if websocket.scheme == "wss" else 80)
        if (
            websocket.scheme not in {"ws", "wss"}
            or websocket.hostname not in _LOOPBACK
            or websocket_port != endpoint_port
            or websocket.username
            or websocket.password
            or websocket.query
            or websocket.fragment
            or not websocket.path.startswith("/devtools/browser/")
            or (parsed.scheme in {"ws", "wss"} and websocket.path != parsed.path)
        ):
            return {"endpoint_reachable": False, "endpoint_probe": "IDENTITY_MISMATCH"}
        result["endpoint_reachable"] = True
        targets = read("/json/list")
        if not isinstance(targets, list):
            raise ValueError("Local target inventory is not a list")
        pages = [t for t in targets if isinstance(t, dict) and t.get("type") == "page"]
        result.update(
            page_count=len(pages),
            pdf_like_page_count=sum(
                is_pdf_document_url(str(t.get("url") or ""))
                or str(t.get("title") or "").casefold().endswith(".pdf")
                for t in pages
            ),
            endpoint_probe="COMPLETED",
        )
    except Exception as exc:
        result.update(endpoint_probe="FAILED", probe_error_type=type(exc).__name__)
    return result


def connection_failure_diagnostic(
    exception: Exception,
    *,
    endpoint: str,
    stage: str,
    timeout_seconds: float,
    elapsed_seconds: float,
) -> dict:
    """Explain known stages without treating PDF inventory as a proven cause."""
    timed_out = type(exception).__name__ == "TimeoutError"
    # The SDK's public error call-log can confirm its WebSocket handshake. Do
    # not persist the log: it can contain a browser UUID or other private data.
    connected = (
        True if stage != "cdp_attach" or "<ws connected>" in str(exception) else None
    )
    diagnostic = {
        "schema": "aletheia-nexus/browser-connection-diagnostic/v1",
        "code": "browser_cdp_attach_timeout"
        if timed_out and stage == "cdp_attach"
        else "browser_cdp_attach_failed"
        if stage == "cdp_attach"
        else "browser_context_setup_failed",
        "stage": stage,
        "error_type": type(exception).__name__,
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "websocket_connected": connected,
        "automatic_retry": False,
        "user_state_preserved": True,
        **inspect_local_endpoint(endpoint),
    }
    phase = "本机控制连接" if stage == "cdp_attach" else "安全保护与文件事件监听初始化"
    message = (
        f"浏览器{phase}在 {timeout_seconds:g} 秒内未完成。"
        if timed_out
        else f"浏览器{phase}失败（{type(exception).__name__}）。"
    )
    if stage == "cdp_attach" and connected:
        message += "本机 WebSocket 已连接，但现有页面初始化未完成。"
    if diagnostic.get("endpoint_reachable"):
        message += "本机浏览器控制端点仍能响应。"
    if diagnostic.get("pdf_like_page_count", 0):
        message += (
            f"会话中有 {diagnostic['pdf_like_page_count']} 个可能的 PDF 标签；"
            "这只是排查线索，尚不能确认这些标签就是原因。"
        )
    actions = [
        {
            "action": "retry_task",
            "label": "处理后重试",
            "description": "检查所选浏览器会话后显式重试；本任务不自动重复连接。",
        },
        {
            "action": "choose_profile",
            "label": "选择其他命名会话",
            "description": "可在获取设置中选择其他会话；其机构登录需要另行完成，不迁移登录数据。",
        },
    ]
    if diagnostic.get("pdf_like_page_count", 0):
        actions.insert(
            0,
            {
                "action": "review_pdf_tabs",
                "label": "检查浏览器中的 PDF 标签",
                "description": "先保存阅读进度，再自行决定是否关闭无响应的 PDF 标签后重试；无需关闭整个浏览器。",
            },
        )
    message += (
        "现有窗口、标签和登录状态已保留。请检查后重试，或选择其他命名会话；"
        "已验证正文可使用“仅补取 SI”。"
    )
    diagnostic.update(message=message, recovery_actions=actions)
    return diagnostic
