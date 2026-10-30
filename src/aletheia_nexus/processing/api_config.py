"""Shared official DeepSeek endpoints; credentials never belong in URLs."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def validate_deepseek_base_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("请填写 DeepSeek 官方接口地址。")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("DeepSeek 接口地址格式无效。") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.deepseek.com"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in {"", "/v1"}
    ):
        raise ValueError(
            "当前支持 https://api.deepseek.com 或其 /v1 接口；"
            "地址中不能包含密钥、查询参数或其他代理。"
        )
    return DEFAULT_DEEPSEEK_BASE_URL + parsed.path.rstrip("/")


def resolve_deepseek_endpoint(resource: str, *, base_url: str | None = None) -> str:
    if resource not in {"responses", "models"}:
        raise ValueError("不支持的 DeepSeek 接口类型。")
    selected = (
        (os.environ.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_DEEPSEEK_BASE_URL)
        if base_url is None
        else base_url
    )
    return validate_deepseek_base_url(selected) + "/" + resource
