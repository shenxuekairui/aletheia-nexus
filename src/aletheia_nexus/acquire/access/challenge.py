import re
from html import unescape

from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport

_WS = re.compile(r"\s+")


def _normalize(value: str) -> str:
    value = unescape(value or "").lower()
    return _WS.sub(" ", value).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if term in text)


_CAPTCHA_TERMS = (
    "g-recaptcha",
    "recaptcha",
    "hcaptcha",
    "h-captcha",
    "cf-turnstile",
    "turnstile",
    "captcha",
    "verify you are human",
    "verify that you are human",
    "human verification",
)
_MFA_TERMS = (
    "multi-factor authentication",
    "multifactor authentication",
    "two-factor authentication",
    "2-factor authentication",
    "verification code",
    "one-time password",
    "one time password",
    "security code",
    "authenticator app",
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
    "get access to this article",
)
_DENIED_TERMS = (
    "access denied",
    "request blocked",
    "request has been blocked",
    "you have been blocked",
    "forbidden",
)


def classify_access_challenge(
    *,
    title: str = "",
    url: str = "",
    html: str = "",
) -> ChallengeReport:
    """Classify strong browser-access signals without publisher-specific rules.

    The classifier deliberately requires explicit challenge/access language.
    Generic article-page navigation such as a harmless "Sign in" header does
    not by itself become an authentication challenge.
    """

    title_text = _normalize(title)
    url_text = _normalize(url)
    html_text = _normalize(html)
    combined = " ".join((title_text, url_text, html_text))

    hits = _contains_any(combined, _CAPTCHA_TERMS)
    if hits:
        return ChallengeReport(
            kind=ChallengeKind.CAPTCHA,
            evidence=tuple(f"CAPTCHA signal: {term}" for term in hits[:3]),
        )

    hits = _contains_any(combined, _MFA_TERMS)
    if hits:
        return ChallengeReport(
            kind=ChallengeKind.MFA,
            evidence=tuple(f"MFA signal: {term}" for term in hits[:3]),
        )

    hits = _contains_any(combined, _BOT_TERMS)
    if hits or title_text in {"just a moment", "just a moment..."}:
        evidence = [f"Bot challenge signal: {term}" for term in hits[:3]]
        if title_text in {"just a moment", "just a moment..."}:
            evidence.append("Bot challenge title: just a moment")
        return ChallengeReport(
            kind=ChallengeKind.BOT_CHALLENGE,
            evidence=tuple(evidence),
        )

    hits = _contains_any(combined, _DENIED_TERMS)
    if hits:
        return ChallengeReport(
            kind=ChallengeKind.ACCESS_DENIED,
            evidence=tuple(f"Access-denied signal: {term}" for term in hits[:3]),
        )

    # Prefer an explicit institutional/SSO path over a generic paywall marker.
    # Many legitimate subscription pages show both at the same time; reporting
    # ENTITLEMENT too early would prevent the user from authenticating through
    # access they already possess.
    sso_hits = _contains_any(combined, _SSO_TERMS)
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
    if sso_hits and (login_url or "institution" in title_text or "sign in" in title_text):
        return ChallengeReport(
            kind=ChallengeKind.SSO,
            evidence=tuple(f"SSO signal: {term}" for term in sso_hits[:3]),
        )

    auth_hits = _contains_any(combined, _AUTH_TERMS)
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

    hits = _contains_any(combined, _ENTITLEMENT_TERMS)
    if hits:
        return ChallengeReport(
            kind=ChallengeKind.ENTITLEMENT,
            evidence=tuple(f"Entitlement signal: {term}" for term in hits[:3]),
        )

    return ChallengeReport(kind=ChallengeKind.NONE)
