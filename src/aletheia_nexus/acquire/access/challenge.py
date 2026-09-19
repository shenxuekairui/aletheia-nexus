import re
from html import unescape

from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport

_WS = re.compile(r"\s+")


def _normalize(value: str) -> str:
    value = unescape(value or "").lower()
    return _WS.sub(" ", value).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if term in text)


_CAPTCHA_VISIBLE_TERMS = (
    "verify you are human",
    "verify that you are human",
    "prove you are human",
    "human verification required",
)
_CAPTCHA_DOM_TERMS = (
    'class="g-recaptcha',
    "class='g-recaptcha",
    'class="h-captcha',
    "class='h-captcha",
    'class="cf-turnstile',
    "class='cf-turnstile",
    "recaptcha/api2/anchor",
    "hcaptcha.com/captcha",
    "turnstile/v0/",
)
_MFA_TERMS = (
    "enter the verification code",
    "enter your verification code",
    "enter the security code",
    "enter your security code",
    "enter the one-time password",
    "enter your one-time password",
    "enter the one time password",
    "code from your authenticator app",
    "open your authenticator app",
    "multi-factor authentication required",
    "multifactor authentication required",
    "two-factor authentication required",
    "2-factor authentication required",
)
_BOT_TERMS = (
    "checking your browser",
    "checking if the site connection is secure",
    "performing security verification",
    "security check",
    "enable javascript and cookies to continue",
    "please wait while we verify",
    "browser verification",
)
_SSO_TERMS = (
    "single sign-on",
    "single sign on",
    "institutional sign in",
    "institutional login",
    "sign in through your institution",
    "access through your institution",
    "shibboleth",
    "openathens",
)
_AUTH_TERMS = (
    "sign in to access",
    "log in to access",
    "login to access",
    "sign in to continue",
    "log in to continue",
    "login to continue",
    "authentication required",
    "please sign in",
    "please log in",
)
_ENTITLEMENT_TERMS = (
    "your institution does not have access",
    "your organization does not have access",
    "subscription required to access",
    "purchase this article",
    "rent or buy",
    "buy this article",
)
_DENIED_TERMS = (
    "access denied",
    "request blocked",
    "request has been blocked",
    "you have been blocked",
    "403 forbidden",
)


def classify_access_challenge(
    *,
    title: str = "",
    url: str = "",
    visible_text: str = "",
    html: str = "",
) -> ChallengeReport:
    """Classify strong browser-access signals without publisher-specific rules.

    Visible text drives semantic classification. Raw HTML is used only for strong
    structural CAPTCHA widget markers so harmless script bundles mentioning
    challenge libraries do not turn a normal article page into a false block.
    """

    title_text = _normalize(title)
    url_text = _normalize(url)
    visible = _normalize(visible_text)
    html_text = _normalize(html)
    # Challenge language should normally be near the access surface, not buried
    # deep inside a scholarly article. Bound visible text to reduce topical
    # false positives while retaining login/challenge content.
    semantic = " ".join((title_text, url_text, visible[:50_000]))

    visible_hits = _contains_any(semantic, _CAPTCHA_VISIBLE_TERMS)
    dom_hits = _contains_any(html_text, _CAPTCHA_DOM_TERMS)
    if visible_hits or dom_hits:
        evidence = [
            *(f"CAPTCHA visible signal: {term}" for term in visible_hits[:2]),
            *(f"CAPTCHA DOM signal: {term}" for term in dom_hits[:2]),
        ]
        return ChallengeReport(
            kind=ChallengeKind.CAPTCHA,
            evidence=tuple(evidence),
        )

    hits = _contains_any(semantic, _MFA_TERMS)
    if hits:
        return ChallengeReport(
            kind=ChallengeKind.MFA,
            evidence=tuple(f"MFA signal: {term}" for term in hits[:3]),
        )

    hits = _contains_any(semantic, _BOT_TERMS)
    if hits or title_text in {"just a moment", "just a moment..."}:
        evidence = [f"Bot challenge signal: {term}" for term in hits[:3]]
        if title_text in {"just a moment", "just a moment..."}:
            evidence.append("Bot challenge title: just a moment")
        return ChallengeReport(
            kind=ChallengeKind.BOT_CHALLENGE,
            evidence=tuple(evidence),
        )

    hits = _contains_any(semantic, _DENIED_TERMS)
    if hits:
        return ChallengeReport(
            kind=ChallengeKind.ACCESS_DENIED,
            evidence=tuple(f"Access-denied signal: {term}" for term in hits[:3]),
        )

    # Prefer an explicit institutional/SSO path over a generic paywall marker.
    # Legitimate subscription pages frequently show both at the same time.
    sso_hits = _contains_any(semantic, _SSO_TERMS)
    entitlement_hits = _contains_any(semantic, _ENTITLEMENT_TERMS)
    login_url = any(
        marker in url_text
        for marker in (
            "/login",
            "/signin",
            "/sign-in",
            "/sso",
            "/shibboleth",
            "/openathens",
        )
    )
    if sso_hits and (
        login_url
        or entitlement_hits
        or "institution" in title_text
        or "sign in" in title_text
    ):
        return ChallengeReport(
            kind=ChallengeKind.SSO,
            evidence=tuple(f"SSO signal: {term}" for term in sso_hits[:3]),
        )

    auth_hits = _contains_any(semantic, _AUTH_TERMS)
    if auth_hits or (
        login_url
        and any(marker in title_text for marker in ("sign in", "log in", "login"))
    ):
        evidence = [f"Authentication signal: {term}" for term in auth_hits[:3]]
        if login_url:
            evidence.append("Authentication-like URL")
        return ChallengeReport(
            kind=ChallengeKind.AUTHENTICATION,
            evidence=tuple(evidence),
        )

    if entitlement_hits:
        return ChallengeReport(
            kind=ChallengeKind.ENTITLEMENT,
            evidence=tuple(
                f"Entitlement signal: {term}" for term in entitlement_hits[:3]
            ),
        )

    return ChallengeReport(kind=ChallengeKind.NONE)
