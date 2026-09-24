import re
from html import unescape

from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport

_WS = re.compile(r"\s+")

_MAX_TITLE = 4_096
_MAX_URL = 16_384
_MAX_VISIBLE_TEXT = 100_000
_MAX_HTML = 500_000


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
    "are you a robot",
    "please confirm you are a human",
    "captcha challenge below",
    "请完成人机验证",
    "人机验证",
    "图形验证码",
    "drag the slider to verify",
    "slide to verify",
    "slider verification",
    "请拖动滑块",
    "拖动滑块完成验证",
    "滑块验证",
)
_CAPTCHA_WIDGET_TERMS = (
    'class="g-recaptcha',
    "class='g-recaptcha",
    'class="h-captcha',
    "class='h-captcha",
    'class="cf-turnstile',
    "class='cf-turnstile",
)
_CAPTCHA_DOM_TERMS = (
    "recaptcha/api2/anchor",
    "hcaptcha.com/captcha",
    "turnstile/v0/",
    "challenges.cloudflare.com/cdn-cgi/challenge-platform",
    "/turnstile/",
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
    "请输入短信验证码",
    "请输入手机验证码",
    "请输入动态验证码",
    "短信验证码",
    "手机验证码",
    "动态验证码",
    "二次验证",
    "approve sign in request",
    "approve the sign-in request",
    "approve the sign in request",
    "check your authenticator app",
    "we sent a notification to your mobile device",
    "批准登录请求",
    "请批准登录请求",
    "请在身份验证器应用中批准",
    "请在 authenticator 中批准",
)
_BOT_TERMS = (
    "checking your browser",
    "checking if the site connection is secure",
    "performing security verification",
    "security check",
    "enable javascript and cookies to continue",
    "please wait while we verify",
    "browser verification",
    "正在进行安全验证",
    "请稍候，我们正在验证",
    "正在验证您的浏览器",
)
_BOT_URL_MARKERS = (
    "__cf_chl_",
    "/cdn-cgi/challenge-platform/",
)
_SSO_TERMS = (
    "single sign-on",
    "single sign on",
    "institutional sign in",
    "institutional login",
    "sign in through your institution",
    "access through your institution",
    "access through your organization",
    "access through your organisation",
    "choose your institution",
    "select your institution",
    "find your institution",
    "shibboleth",
    "openathens",
    "统一身份认证",
    "机构登录",
    "机构认证",
    "选择机构",
    "选择您的机构",
    "查找您的机构",
    "选择组织",
    "选择您的组织",
    "查找您的组织",
    "组织登录",
    "组织认证",
    "使用中国科技云通行证登录",
    "中国科技云通行证账号登录",
    "carsi",
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
    "请登录后访问",
    "请先登录",
    "登录后访问",
    "您正在登录",
)
_ENTITLEMENT_TERMS = (
    "your institution does not have access",
    "your organization does not have access",
    "subscription required to access",
    "purchase this article",
    "rent or buy",
    "buy this article",
    "sign in or purchase",
    "you do not have access to this pdf",
    "您的机构没有访问权限",
    "您的机构无权访问",
    "当前机构没有访问权限",
    "暂无访问权限",
)
_DENIED_TERMS = (
    "access denied",
    "request blocked",
    "request has been blocked",
    "you have been blocked",
    "403 forbidden",
    "unusual traffic detected",
    "unusual request pattern",
    "拒绝访问",
    "请求已被阻止",
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

    # Bound normalization work before allocating normalized copies. Challenge
    # surfaces are small; scanning entire article/script payloads adds cost and
    # increases false-positive exposure without improving access classification.
    title_text = _normalize(title[:_MAX_TITLE])
    url_text = _normalize(url[:_MAX_URL])
    visible = _normalize(visible_text[:_MAX_VISIBLE_TEXT])
    html_text = _normalize(html[:_MAX_HTML])
    # Challenge language should normally be near the access surface, not buried
    # deep inside a scholarly article. Bound visible text to reduce topical
    # false positives while retaining login/challenge content.
    semantic = " ".join((title_text, url_text, visible[:50_000]))

    visible_hits = _contains_any(semantic, _CAPTCHA_VISIBLE_TERMS)
    widget_hits = _contains_any(html_text, _CAPTCHA_WIDGET_TERMS)
    dom_hits = _contains_any(html_text, _CAPTCHA_DOM_TERMS)
    captcha_surface = any(
        marker in " ".join((title_text, url_text))
        for marker in (
            "captcha",
            "challenge",
            "security check",
            "security verification",
            "verify you are human",
            "verify that you are human",
            "human verification",
            "人机验证",
            "安全验证",
        )
    )
    if visible_hits or dom_hits or (widget_hits and captcha_surface):
        evidence = [
            *(f"CAPTCHA visible signal: {term}" for term in visible_hits[:2]),
            *(
                f"CAPTCHA widget signal: {term}"
                for term in widget_hits[:2]
                if captcha_surface
            ),
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
    url_hits = _contains_any(url_text, _BOT_URL_MARKERS)
    url_is_challenge_surface = bool(url_hits) and not (
        title_text.endswith(".pdf") or (title_text and len(visible) > 50 and not hits)
    )
    if (
        hits
        or url_is_challenge_surface
        or title_text in {"just a moment", "just a moment..."}
    ):
        evidence = [f"Bot challenge signal: {term}" for term in hits[:3]]
        if url_is_challenge_surface:
            evidence.extend(
                f"Bot challenge URL marker: {term}" for term in url_hits[:2]
            )
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
            "/oauth",
            "/authorize",
            "/saml",
            "/cas/",
        )
    )
    auth_hits = _contains_any(semantic, _AUTH_TERMS)

    # Institutional terminology also appears in ordinary article chrome and in
    # scholarly content about authentication itself. Require evidence that the
    # text belongs to the current access surface rather than treating one keyword
    # as a challenge.
    sso_title_markers = (
        "institutional sign in",
        "institutional login",
        "choose your institution",
        "select your institution",
        "find your institution",
        "access through your organization",
        "access through your organisation",
        "选择机构",
        "选择您的机构",
        "查找您的机构",
        "选择组织",
        "选择您的组织",
        "查找您的组织",
        "组织登录",
        "组织认证",
        "single sign-on",
        "single sign on",
        "统一身份认证",
        "机构登录",
        "机构认证",
        "中国科技云通行证登录",
    )
    title_is_access_surface = any(
        title_text == marker
        or (title_text.startswith(marker) and len(title_text) <= len(marker) + 24)
        for marker in sso_title_markers
    )
    visible_is_access_surface = any(
        visible == term or (visible.startswith(term) and len(visible) <= len(term) + 80)
        for term in sso_hits
    )
    multiple_sso_signals = len(set(sso_hits)) >= 2

    if sso_hits and (
        login_url
        or entitlement_hits
        or auth_hits
        or title_is_access_surface
        or visible_is_access_surface
        or multiple_sso_signals
    ):
        evidence = [f"SSO signal: {term}" for term in sso_hits[:3]]
        if login_url:
            evidence.append("SSO/login-like URL")
        if entitlement_hits:
            evidence.append(
                "Institutional access option appears at an entitlement boundary"
            )
        if title_is_access_surface:
            evidence.append("Page title is an institutional authentication surface")
        return ChallengeReport(
            kind=ChallengeKind.SSO,
            evidence=tuple(evidence),
        )

    if auth_hits or (
        login_url
        and any(
            marker in title_text
            for marker in ("sign in", "log in", "login", "登录", "认证")
        )
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
