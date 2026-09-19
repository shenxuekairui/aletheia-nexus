from aletheia_nexus.acquire.access import (
    ChallengeKind,
    classify_access_challenge,
)


def test_harmless_global_sign_in_is_not_an_auth_challenge():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="Sign in Article abstract",
        html="<header><a>Sign in</a></header><main>Article abstract</main>",
    )
    assert report.kind == ChallengeKind.NONE


def test_captcha_is_explicitly_classified():
    report = classify_access_challenge(
        title="Verify you are human",
        url="https://publisher.example/challenge",
        html='<div class="g-recaptcha">Verify you are human</div>',
    )
    assert report.kind == ChallengeKind.CAPTCHA


def test_institutional_sso_outranks_generic_purchase_language():
    report = classify_access_challenge(
        title="Institutional sign in",
        url="https://publisher.example/login",
        visible_text="Purchase this article Access through your institution",
        html="<p>Purchase this article</p><a>Access through your institution</a>",
    )
    assert report.kind == ChallengeKind.SSO


def test_mfa_is_distinguished_from_plain_login():
    report = classify_access_challenge(
        title="Verification",
        url="https://idp.example/login",
        visible_text="Enter the verification code from your authenticator app",
        html="<p>Enter the verification code from your authenticator app</p>",
    )
    assert report.kind == ChallengeKind.MFA


def test_explicit_no_entitlement_is_not_called_authentication():
    report = classify_access_challenge(
        title="Access options",
        url="https://publisher.example/article",
        visible_text="Your institution does not have access",
        html="<p>Your institution does not have access</p>",
    )
    assert report.kind == ChallengeKind.ENTITLEMENT


def test_explicit_block_is_access_denied():
    report = classify_access_challenge(
        title="Access denied",
        url="https://publisher.example/article",
        visible_text="Your request has been blocked",
        html="<p>Your request has been blocked</p>",
    )
    assert report.kind == ChallengeKind.ACCESS_DENIED


def test_optional_institution_link_on_accessible_article_is_not_a_challenge():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="Full article text Access through your institution",
        html="<main>Full article text</main><a>Access through your institution</a>",
    )
    assert report.kind == ChallengeKind.NONE


def test_loaded_recaptcha_library_without_active_widget_is_not_a_challenge():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="Full article text",
        html=(
            "<main>Full article text</main>"
            '<script src="https://www.google.com/recaptcha/api.js"></script>'
        ),
    )
    assert report.kind == ChallengeKind.NONE



def test_article_about_captcha_is_not_itself_a_captcha_challenge():
    report = classify_access_challenge(
        title="CAPTCHA robustness in web security",
        url="https://publisher.example/article",
        visible_text=(
            "CAPTCHA systems are widely studied. "
            "This article compares verification methods."
        ),
        html="<main>CAPTCHA systems are widely studied.</main>",
    )
    assert report.kind == ChallengeKind.NONE


def test_article_about_multifactor_authentication_is_not_mfa_prompt():
    report = classify_access_challenge(
        title="Multi-factor authentication in distributed systems",
        url="https://publisher.example/article",
        visible_text=(
            "Multi-factor authentication and security codes are discussed "
            "as research topics in this article."
        ),
        html="<main>Research article text</main>",
    )
    assert report.kind == ChallengeKind.NONE


def test_imperative_mfa_prompt_is_still_detected():
    report = classify_access_challenge(
        title="Verification",
        url="https://idp.example/login",
        visible_text="Enter your verification code from your authenticator app",
        html="<main>Enter your verification code from your authenticator app</main>",
    )
    assert report.kind == ChallengeKind.MFA
