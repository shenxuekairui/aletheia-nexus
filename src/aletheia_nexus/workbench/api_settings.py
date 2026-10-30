"""Session API configuration and optional workspace-scoped Windows credentials.

No credential operation happens on import. Secrets are never preferences or task
parameters; Windows stores only an explicitly requested user GenericCredential.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
from threading import RLock

import httpx

from aletheia_nexus.processing.api_config import (
    DEFAULT_DEEPSEEK_BASE_URL,
    resolve_deepseek_endpoint,
    validate_deepseek_base_url,
)

_AUTO = object()
_KEY_ENV = "DEEPSEEK_API_KEY"
_BASE_ENV = "DEEPSEEK_BASE_URL"


class _SafeConnectionError(ValueError):
    pass


def credential_target(workspace) -> str:
    identity = os.path.normcase(str(Path(workspace).resolve()))
    return (
        "AletheiaNexus:DeepSeek:workspace:"
        + hashlib.sha256(identity.encode()).hexdigest()
    )


class _FILETIME(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.c_uint32),
        ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


class WindowsCredentialStore:
    """User Credential Manager, with an injectable WinAPI for isolated tests."""

    def __init__(self, *, api=None):
        if api is None:
            if os.name != "nt":
                raise OSError("当前系统不提供 Windows 用户凭据管理器。")
            api = ctypes.WinDLL("Advapi32", use_last_error=True)
        self.api = api
        signatures = {
            "CredReadW": (
                [
                    ctypes.c_wchar_p,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
                ],
                ctypes.c_int32,
            ),
            "CredWriteW": (
                [ctypes.POINTER(_CREDENTIALW), ctypes.c_uint32],
                ctypes.c_int32,
            ),
            "CredDeleteW": (
                [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32],
                ctypes.c_int32,
            ),
            "CredFree": ([ctypes.c_void_p], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(api, name)
            try:
                function.argtypes, function.restype = arguments, result
            except AttributeError:
                pass  # A fake bound method still exercises the real structures.

    def _error(self):
        return (
            self.api.get_last_error()
            if hasattr(self.api, "get_last_error")
            else ctypes.get_last_error()
        )

    def read(self, target):
        pointer = ctypes.POINTER(_CREDENTIALW)()
        if not self.api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            if self._error() == 1168:  # ERROR_NOT_FOUND
                return None
            raise ValueError("无法读取 Windows 用户凭据，请在设置中重新填写密钥。")
        try:
            value = pointer.contents
            if not 0 < value.CredentialBlobSize <= 2560 or value.CredentialBlobSize % 2:
                raise ValueError("已保存的 Windows 凭据格式无效，请重新保存。")
            return ctypes.string_at(
                value.CredentialBlob, value.CredentialBlobSize
            ).decode("utf-16-le")
        except UnicodeError:
            raise ValueError("已保存的 Windows 凭据编码无效，请重新保存。") from None
        finally:
            self.api.CredFree(pointer)

    def write(self, target, secret):
        encoded = secret.encode("utf-16-le")
        if len(encoded) > 2560:
            raise ValueError("密钥超过 Windows 凭据大小上限，可改用仅本次会话。")
        blob = ctypes.create_string_buffer(encoded)
        credential = _CREDENTIALW()
        credential.Type, credential.Persist = (
            1,
            2,
        )  # Generic, current user/local machine.
        credential.TargetName = target
        credential.Comment = "Aletheia Nexus workspace API credential"
        credential.UserName = "AletheiaNexus"
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        try:
            if not self.api.CredWriteW(ctypes.byref(credential), 0):
                raise ValueError("无法保存到 Windows 用户凭据管理器；本次会话未更改。")
        finally:
            ctypes.memset(blob, 0, len(encoded))

    def delete(self, target):
        if self.api.CredDeleteW(target, 1, 0):
            return True
        if self._error() == 1168:
            return False
        raise ValueError("无法删除此工作区的 Windows 凭据，请检查用户凭据管理器。")


def _backend(selected):
    if selected is not _AUTO:
        return selected
    if os.name != "nt":
        return None
    try:
        return WindowsCredentialStore()
    except OSError:
        return None


def _key(value):
    if not isinstance(value, str):
        raise ValueError("请以文字形式填写 API 密钥。")
    value = value.strip()
    if (
        not value
        or len(value) > 2048
        or any(not 33 <= ord(char) <= 126 for char in value)
    ):
        raise ValueError("请填写不含空白或控制字符的有效 API 密钥。")
    return value


def _preferences(settings):
    value = settings.get("api", {})
    return value if isinstance(value, dict) else {}


def load_saved_api_credentials(
    workspace, settings=None, *, credential_backend=_AUTO, environ=None
):
    """Load only this workspace's saved key when an environment key is absent."""
    from .settings import SettingsStore

    settings = settings if settings is not None else SettingsStore(workspace)
    environ = os.environ if environ is None else environ
    backend = _backend(credential_backend)
    source, key_loaded, base_loaded, warning = "environment", False, False, None
    if not environ.get(_BASE_ENV, "").strip() and _preferences(settings).get(
        "base_url"
    ):
        try:
            environ[_BASE_ENV] = validate_deepseek_base_url(
                _preferences(settings)["base_url"]
            )
            base_loaded = True
        except ValueError:
            warning = "已保存接口地址不符合当前安全规则，请在 API 设置中修正。"
    if not environ.get(_KEY_ENV, "").strip() and backend is not None:
        try:
            saved = backend.read(credential_target(workspace))
            if saved:
                environ[_KEY_ENV] = _key(saved)
                source, key_loaded = "windows", True
        except Exception:
            warning = "无法载入此工作区已保存的凭据；本地功能仍可使用，请在 API 设置重新填写。"
    configured = bool(environ.get(_KEY_ENV, "").strip())
    try:
        base = validate_deepseek_base_url(
            environ.get(_BASE_ENV) or DEFAULT_DEEPSEEK_BASE_URL
        )
    except ValueError:
        base = DEFAULT_DEEPSEEK_BASE_URL
        warning = "当前接口地址不符合安全规则，远程调用将被拒绝；请在 API 设置中修正。"
    return {
        "configured": configured,
        "source": source if configured else "missing",
        "base_url": base,
        "key_loaded": key_loaded,
        "base_url_loaded": base_loaded,
        "persistence_supported": backend is not None,
        "warning": warning,
    }


class ApiSettingsService:
    def __init__(
        self,
        settings,
        workspace,
        *,
        can_change,
        credential_backend=_AUTO,
        environ=None,
        source=None,
    ):
        self.settings, self.workspace = settings, Path(workspace).resolve()
        self.environ = os.environ if environ is None else environ
        self.backend, self.can_change = _backend(credential_backend), can_change
        self._source = (
            source.get("source", "environment")
            if isinstance(source, dict)
            else source or "environment"
        )
        self._load_warning = source.get("warning") if isinstance(source, dict) else None
        self._lock = RLock()

    def status(self):
        configured = bool(self.environ.get(_KEY_ENV, "").strip())
        warning = self._load_warning
        try:
            base = validate_deepseek_base_url(
                self.environ.get(_BASE_ENV)
                or _preferences(self.settings).get("base_url")
                or DEFAULT_DEEPSEEK_BASE_URL
            )
        except ValueError:
            base = DEFAULT_DEEPSEEK_BASE_URL
            warning = "现有接口地址不符合安全规则，请核对并保存正确的官方地址。"
        return {
            "configured": configured,
            "source": self._source if configured else "missing",
            "base_url": base,
            "persistence_supported": self.backend is not None,
            "saved_storage": _preferences(self.settings).get("storage"),
            "warning": warning,
        }

    def save(self, *, base_url, api_key="", persist=False):
        base = validate_deepseek_base_url(base_url)
        if not isinstance(api_key, str) or type(persist) is not bool:
            raise ValueError("请使用密钥输入框，并明确选择是否保存到 Windows。")
        selected_key = (
            _key(api_key) if api_key.strip() else self.environ.get(_KEY_ENV, "").strip()
        )
        if persist and self.backend is None:
            raise ValueError(
                "当前平台不支持 Windows 凭据保存；请选择仅本次会话或环境变量方式。"
            )
        if persist and not selected_key:
            raise ValueError("请先填写 API 密钥，再选择跨重启保存。")
        if persist and len(selected_key.encode("utf-16-le")) > 2560:
            raise ValueError("密钥超过 Windows 凭据大小上限，可改用仅本次会话。")
        with self._lock:
            if not self.can_change():
                raise ValueError(
                    "仍有任务正在运行或等待处理，请在任务结束后修改 API 密钥或接口地址。"
                )
            previous = _preferences(self.settings)
            updated = {**previous, "base_url": base}
            if persist:
                updated["storage"] = "windows"
            try:
                self.settings.set("api", updated)
            except Exception:
                raise ValueError(
                    "无法保存 API 接口偏好；密钥及当前会话未更改，请检查工作区。"
                ) from None
            if persist:
                try:
                    self.backend.write(credential_target(self.workspace), selected_key)
                except Exception:
                    try:
                        self.settings.set("api", previous)
                    except Exception:
                        raise ValueError(
                            "保存 Windows 凭据失败且接口偏好未能回滚；当前会话未切换，请检查工作区与凭据管理器。"
                        ) from None
                    raise ValueError(
                        "保存 Windows 凭据失败；接口偏好已恢复，当前会话未更改。"
                    ) from None
            self.environ[_BASE_ENV] = base
            if api_key.strip():
                self.environ[_KEY_ENV] = selected_key
                self._source = "session"
            self._load_warning = None
        return self.status()

    def check_connection(self, *, base_url=None, api_key="", transport=None):
        # Capture one non-mutating request. Checking never starts a model task,
        # sends paper content, saves a key, or follows an authentication redirect.
        if not isinstance(api_key, str):
            raise ValueError("请以文字形式填写 API 密钥。")
        base = validate_deepseek_base_url(
            base_url
            if base_url is not None
            else self.environ.get(_BASE_ENV)
            or _preferences(self.settings).get("base_url")
            or DEFAULT_DEEPSEEK_BASE_URL
        )
        secret = _key(api_key if api_key.strip() else self.environ.get(_KEY_ENV, ""))
        try:
            with httpx.Client(
                transport=transport, timeout=10, follow_redirects=False
            ) as client:
                with client.stream(
                    "GET",
                    resolve_deepseek_endpoint("models", base_url=base),
                    headers={
                        "Authorization": "Bearer " + secret,
                        "Accept": "application/json",
                    },
                ) as response:
                    status = response.status_code
                    if status != 200:
                        messages = {
                            401: "密钥未通过认证，请检查密钥。",
                            403: "接口拒绝访问，请检查账户权限。",
                            429: "接口暂时限流，请稍后再检查。",
                        }
                        return {
                            "ok": False,
                            "http_status": status,
                            "message": messages.get(
                                status, "接口未返回成功状态；没有发送论文或调用模型。"
                            ),
                        }
                    body = bytearray()
                    for part in response.iter_bytes():
                        body.extend(part)
                        if len(body) > 131072:
                            raise _SafeConnectionError(
                                "连接检查响应过大，已停止读取；没有调用模型。"
                            )
                    data = json.loads(body)
                    if not isinstance(data, dict) or not isinstance(
                        data.get("data"), list
                    ):
                        raise _SafeConnectionError(
                            "连接检查响应格式不符；没有发送论文或调用模型。"
                        )
                    return {
                        "ok": True,
                        "http_status": 200,
                        "models_count": len(data["data"]),
                        "message": "连接检查成功；仅查询模型列表，未发送论文或生成内容。",
                    }
        except _SafeConnectionError as exc:
            raise ValueError(str(exc)) from None
        except json.JSONDecodeError:
            raise ValueError("连接检查未得到有效模型列表；请核对接口地址。") from None
        except Exception:
            raise ValueError(
                "连接检查失败，请检查网络、系统代理和接口地址；密钥不会显示在诊断中。"
            ) from None
