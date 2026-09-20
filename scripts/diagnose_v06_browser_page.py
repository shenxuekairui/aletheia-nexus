import argparse
from pathlib import Path

from aletheia_nexus.acquire.access import BrowserAccessConfig, browser_profile_dir
from aletheia_nexus.acquire.access.security import redact_url_for_record

KEYWORDS = (
    "pdf",
    "access",
    "institution",
    "organization",
    "organisation",
    "sign in",
    "log in",
    "verify",
    "captcha",
    "human",
    "purchase",
)

INTERACTIVE_SELECTOR = (
    "a, button, [role='button'], [role='link'], input, "
    "[aria-label], [title]"
)


def _safe(value: str | None, limit: int = 300) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())[:limit]


def _safe_href(value: str | None) -> str:
    if not value:
        return ""
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        return redact_url_for_record(value) or "[unparseable-url]"
    return _safe(value)


def _describe(locator) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        values["text"] = _safe(locator.inner_text(timeout=1000))
    except Exception:
        values["text"] = ""

    for name in ("aria-label", "title", "href", "role", "data-testid"):
        try:
            value = locator.get_attribute(name)
        except Exception:
            value = None
        values[name] = _safe_href(value) if name == "href" else _safe(value)

    try:
        values["tag"] = _safe(locator.evaluate("(el) => el.tagName"))
    except Exception:
        values["tag"] = ""

    return values


def _matches(values: dict[str, str]) -> bool:
    haystack = " ".join(values.values()).lower()
    return any(keyword in haystack for keyword in KEYWORDS)


def _print_frame(frame, index: int) -> None:
    print()
    print("=" * 80)
    print(f"FRAME #{index}")
    print("=" * 80)
    print("URL:", redact_url_for_record(frame.url) or "")

    try:
        print("TITLE:", _safe(frame.title()))
    except Exception:
        print("TITLE:")

    print()
    print("Relevant interactive elements:")

    try:
        locator = frame.locator(INTERACTIVE_SELECTOR)
        count = min(locator.count(), 300)
    except Exception as exc:
        print("  <unable to enumerate>", type(exc).__name__)
        return

    found = 0
    for item_index in range(count):
        item = locator.nth(item_index)
        values = _describe(item)
        if not _matches(values):
            continue
        found += 1
        print(f"  [{found}] index={item_index}")
        for key in ("tag", "role", "text", "aria-label", "title", "href", "data-testid"):
            if values[key]:
                print(f"      {key}: {values[key]}")

    if found == 0:
        print("  <none>")

    print()
    print("Relevant visible-text nodes:")

    try:
        text_locator = frame.locator("body *")
        text_count = min(text_locator.count(), 3000)
    except Exception as exc:
        print("  <unable to enumerate>", type(exc).__name__)
        return

    found_text = 0
    seen: set[str] = set()
    for item_index in range(text_count):
        item = text_locator.nth(item_index)
        try:
            text = _safe(item.inner_text(timeout=300), limit=220)
        except Exception:
            continue
        lowered = text.lower()
        if (
            not text
            or len(text) > 220
            or text in seen
            or not any(keyword in lowered for keyword in KEYWORDS)
        ):
            continue
        seen.add(text)
        values = _describe(item)
        found_text += 1
        print(f"  [{found_text}] index={item_index}")
        for key in ("tag", "role", "text", "aria-label", "title", "href", "data-testid"):
            if values[key]:
                print(f"      {key}: {values[key]}")
        if found_text >= 80:
            print("  <truncated after 80 matches>")
            break

    if found_text == 0:
        print("  <none>")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely inspect a live publisher page for v0.6 browser routing."
    )
    parser.add_argument("url")
    parser.add_argument("--profile-name", default="institution")
    parser.add_argument("--channel", default=None)
    parser.add_argument("--wait-seconds", type=float, default=5.0)
    args = parser.parse_args()

    if args.wait_seconds < 0:
        parser.error("--wait-seconds must be non-negative")

    config = BrowserAccessConfig(
        profile_name=args.profile_name,
        headless=False,
        interactive=False,
        channel=args.channel,
    )
    profile = browser_profile_dir(config)

    from playwright.sync_api import sync_playwright

    print("Aletheia Nexus v0.6 browser page diagnostic")
    print("Profile:", profile)
    print("Target:", redact_url_for_record(args.url) or "[unparseable-url]")
    print()
    print("No cookies, storage values, request headers, or page HTML are printed.")

    with sync_playwright() as playwright:
        launch_kwargs: dict[str, object] = {
            "user_data_dir": str(profile),
            "headless": False,
            "accept_downloads": True,
            "service_workers": "allow",
        }
        if args.channel:
            launch_kwargs["channel"] = args.channel

        context = playwright.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=45_000)
            if args.wait_seconds:
                page.wait_for_timeout(args.wait_seconds * 1000)

            print()
            print("Page URL:", redact_url_for_record(page.url) or "")
            print("Frame count:", len(page.frames))

            for index, frame in enumerate(page.frames, start=1):
                _print_frame(frame, index)
        finally:
            context.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
