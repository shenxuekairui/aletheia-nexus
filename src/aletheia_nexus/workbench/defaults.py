"""First-use UI preferences; CLI/MCP engine defaults remain unchanged."""

from importlib.util import find_spec
from pathlib import Path

from aletheia_nexus.acquire.access.browser import browser_profile_dir
from aletheia_nexus.acquire.access.models import BrowserAccessConfig

from .acquisition import get_acquisition_defaults


class _Missing:
    def __deepcopy__(self, memo):
        return self


_MISSING = _Missing()


def ui_acquisition_defaults():
    """Public routes first, followed by an ordinary visible AN browser."""
    values = get_acquisition_defaults()
    values.update(
        public_only=False,
        browser_enabled=True,
        auto_official_api=False,
        interaction_policy="wait",
        interaction_timeout=0.0,
        bulk_interval=1.0,
    )
    values["browser"].update(
        profile_name="human-handoff",
        headless=False,
        interactive=True,
        launch_mode="auto",
        channel=None,
        use_system_proxy=None,
        direct_connection=False,
    )
    return values


def browser_profile_choices(browserconfig=None):
    """List safe first-level profile names without opening authentication data.

    An absent current directory remains a choice: only an explicit acquisition
    may create it. Invalid or linked saved values remain in ``current`` with a
    warning instead of silently selecting a different identity.
    """
    if browserconfig is None:
        browserconfig = ui_acquisition_defaults()["browser"]
    if isinstance(browserconfig, BrowserAccessConfig):
        current, profile_root = browserconfig.profile_name, browserconfig.profile_root
    else:
        current = browserconfig.get("profile_name", BrowserAccessConfig().profile_name)
        profile_root = browserconfig.get("profile_root")
    config = BrowserAccessConfig(profile_root=profile_root)
    root = browser_profile_dir(config).parent.absolute()
    result = {
        "options": [],
        "current": current,
        "root": str(root),
        "message": (
            "选择已有会话可复用该目录中的登录状态；新会话首次可能需要登录。"
            "不会复制认证内容，也不代表已有机构访问权限。"
            "同一会话正在被其他获取任务使用时，请等待完成或选择其他会话。"
        ),
        "warnings": [],
    }

    def linked(path):
        return path.is_symlink() or (
            hasattr(path, "is_junction") and path.is_junction()
        )

    def valid_name(name):
        try:
            browser_profile_dir(BrowserAccessConfig(profile_name=name))
        except (TypeError, ValueError):
            return False
        return True

    if not valid_name(current):
        result["warnings"].append("已保存的会话名称无效，请检查后再获取；未替换原值。")
    else:
        result["options"].append(current)
    try:
        if any(linked(path) for path in (root, *root.parents)):
            result["warnings"].append(
                "会话根目录包含符号链接或目录联接，未读取其中的会话列表。"
            )
            return result
        if valid_name(current) and linked(root / current):
            result["options"].remove(current)
            result["warnings"].append(
                "当前会话目录是符号链接或目录联接，请检查路径；未替换已保存值。"
            )
        for entry in root.iterdir():
            if valid_name(entry.name) and not linked(entry) and entry.is_dir():
                result["options"].append(entry.name)
    except FileNotFoundError:
        pass  # First use: do not create a root merely to populate a selector.
    except OSError as exc:
        result["warnings"].append(
            f"无法读取现有会话目录（{type(exc).__name__}）；已保留当前会话设置。"
        )
    result["options"] = sorted(
        set(result["options"]), key=lambda name: (name.casefold(), name)
    )
    return result


def ui_workflow_defaults():
    """Native local parsing is automatic; OCR and paid translation stay opt-in."""
    return {
        "template": "{year}-{journal}-{title_zh}",
        "folder": "",
        "tags": [],
        "collection": "",
        "auto_parse": True,
        "title_translation": {"enabled": False},
    }


def bootstrap_ui_defaults(settings):
    """Initialize missing sections only; an explicit empty section also counts.

    SettingsStore deep-copies fallback values, hence the identity-preserving
    sentinel. In particular, None/{} are not mistaken for an absent preference.
    Existing presets and saved task parameters are never rewritten.
    """
    initialized, preserved = [], []
    for section, factory in (
        ("acquisition", ui_acquisition_defaults),
        ("acquisition_workflow", ui_workflow_defaults),
    ):
        if settings.get(section, _MISSING) is _MISSING:
            settings.set(section, factory())
            initialized.append(section)
        else:
            preserved.append(section)
    return {"initialized": initialized, "preserved": preserved}


def browser_readiness(parameters=None):
    """Read-only prerequisites, never launch/connect/login or infer entitlement.

    A detected Python dependency is not proof that a browser runtime, profile,
    institution or publisher will allow access. Actual launch keeps the native
    runtime/version guards. The UI should display ``message`` rather than the
    internal status code and can still use public routes when this is missing.
    """
    values = ui_acquisition_defaults() if parameters is None else parameters
    enabled = bool(values.get("browser_enabled") and not values.get("public_only"))
    result = {
        "enabled": enabled,
        "runtime_checked": False,
        "institutional_access_verified": False,
    }
    if not enabled:
        return {
            **result,
            "status": "DISABLED",
            "dependency_installed": None,
            "message": "当前仅使用公开来源；需要机构回退时可选择公开与机构浏览器。",
        }
    if find_spec("playwright") is None:
        return {
            **result,
            "status": "DEPENDENCY_MISSING",
            "dependency_installed": False,
            "message": (
                "机构浏览器缺少 Playwright 依赖；公开来源仍可先行。"
                "请在本分支项目目录安装 UI 依赖后重启，或按安装说明配置浏览器。"
            ),
            "install_command": 'python -m pip install -e ".[ui]"',
        }
    browser = values.get("browser") or {}
    executable = browser.get("executable_path")
    if executable and not Path(executable).expanduser().is_file():
        return {
            **result,
            "status": "EXECUTABLE_MISSING",
            "dependency_installed": True,
            "message": "指定的浏览器程序不存在。请修正程序路径，或清空该覆盖以恢复自动选择本机浏览器。",
        }
    if browser.get("headless") or not browser.get("interactive", True):
        return {
            **result,
            "status": "MANUAL_LOGIN_NOT_VISIBLE",
            "dependency_installed": True,
            "message": (
                "当前配置不能在可见窗口完成新的人工登录。已有会话仍需核验；"
                "需要登录或验证码时，请启用可见、可交互的浏览器。"
            ),
        }
    return {
        **result,
        "status": "READY_TO_ATTEMPT",
        "dependency_installed": True,
        "message": (
            "公开来源先行；必要时尝试打开 AN 独立浏览器，自动选择本机 Chrome/Edge 或已配置运行时。"
            "首次登录或验证由你在可见窗口完成；完成后按下方设置自动检测或手动继续，也可跳过或取消。"
            "浏览器运行时、安全版本与合法访问权限仍在使用时核验。"
        ),
    }
