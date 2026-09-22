import argparse
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    acquire_full_text_maximized,
)
from aletheia_nexus.acquire.access.security import redact_url_for_record
from aletheia_nexus.core.identifiers.doi import normalize_doi

CDP_ENDPOINT = "http://127.0.0.1:9222"


def _find_browser() -> Path:
    candidates = [
        Path.home() / "AppData/Local/Microsoft/Edge/Application/msedge.exe",
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not find Microsoft Edge or Google Chrome in the standard Windows paths."
    )


def _cdp_ready() -> bool:
    try:
        with urlopen(f"{CDP_ENDPOINT}/json/version", timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def _wait_for_cdp(timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _cdp_ready():
            return
        time.sleep(0.25)
    raise RuntimeError(
        "The browser started, but the local debugging endpoint did not become ready."
    )


def _start_browser(doi: str) -> None:
    browser = _find_browser()
    profile = Path.home() / ".aletheia-nexus" / "browser-profiles" / "human-handoff"
    profile.mkdir(parents=True, exist_ok=True)
    target = f"https://doi.org/{doi}"

    subprocess.Popen(
        [
            str(browser),
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile}",
            "--no-proxy-server",
            "--no-first-run",
            "--no-default-browser-check",
            target,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_cdp()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-click v0.6 human browser handoff test."
    )
    parser.add_argument(
        "doi",
        nargs="?",
        default="10.1016/j.apcatb.2025.126129",
        help="DOI to acquire.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("downloads/v06-one-click"),
    )
    args = parser.parse_args()

    doi = normalize_doi(args.doi)

    print("=" * 64)
    print("Aletheia Nexus v0.6 one-click browser handoff")
    print("=" * 64)
    print(f"DOI: {doi}")
    print()

    if not _cdp_ready():
        print("1. 正在启动独立的 Edge/Chrome 浏览器……")
        _start_browser(doi)
    else:
        print("1. 已发现正在运行的 AN 浏览器。")

    print()
    print("2. 请在浏览器中正常完成：")
    print("   - Are you a robot? / CAPTCHA")
    print("   - 机构登录 / CSTCloud / CARSI / SSO / MFA（如果需要）")
    print("   - 最终停在目标论文页面")
    print()
    input("完成后保持论文页面打开，然后回到这里按 Enter：")

    print()
    print("3. AN 正在接管当前浏览器页面并尝试获取、验证 PDF……")
    print()

    config = BrowserAccessConfig(
        profile_name="human-handoff",
        cdp_endpoint=CDP_ENDPOINT,
        headless=False,
        interactive=True,
    )

    result = acquire_full_text_maximized(
        doi,
        output_dir=args.output_dir,
        browser_config=config,
    )

    print("=" * 64)
    print(f"Final status: {result.status.value}")
    if result.verified_path is not None:
        print(f"VERIFIED PDF: {result.verified_path}")
    else:
        print("VERIFIED PDF: -")
    if result.message:
        print(f"Message: {result.message}")

    if result.browser_attempts:
        print()
        print("Browser diagnosis:")
        for index, attempt in enumerate(result.browser_attempts, start=1):
            print(
                f"  [{index}] status={attempt.status.value} "
                f"files={len(attempt.file_attempts)} "
                f"interaction={attempt.interaction_used}"
            )
            if attempt.final_url:
                print(f"      page={redact_url_for_record(attempt.final_url)}")
            if attempt.challenge_history:
                kinds = " -> ".join(
                    report.kind.value for report in attempt.challenge_history
                )
                print(f"      challenges={kinds}")
            if attempt.error:
                print(f"      error={attempt.error}")
            for file_index, file_attempt in enumerate(
                attempt.file_attempts,
                start=1,
            ):
                status = (
                    file_attempt.result.status.value
                    if file_attempt.result is not None
                    else "-"
                )
                print(
                    f"      file[{file_index}] "
                    f"method={file_attempt.method} status={status} "
                    f"error={file_attempt.error or '-'}"
                )
                if file_attempt.result is not None:
                    resource = file_attempt.result.retrieved
                    validation = file_attempt.result.pdf_validation
                    if resource is not None:
                        print(
                            "          response="
                            f"http:{resource.http_status} "
                            f"type:{resource.content_type or '-'} "
                            f"bytes:{resource.size_bytes} "
                            "url:"
                            f"{redact_url_for_record(resource.final_url) or '-'}"
                        )
                    if validation is not None:
                        print(
                            "          pdf="
                            f"magic:{validation.magic_bytes_ok} "
                            f"parseable:{validation.parseable} "
                            f"pages:{validation.page_count} "
                            f"warning:{validation.warning or '-'}"
                        )

    print("=" * 64)

    return 0 if result.verified_path is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
