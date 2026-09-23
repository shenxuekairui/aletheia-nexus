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


def test_pdf_control_no_access_message_is_an_entitlement_boundary():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="PDF You do not have access to this PDF",
    )
    assert report.kind == ChallengeKind.ENTITLEMENT


def test_institution_option_outranks_sign_in_or_purchase_boundary():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="Institutional Sign In Sign In or Purchase",
    )
    assert report.kind == ChallengeKind.SSO


def test_explicit_block_is_access_denied():
    report = classify_access_challenge(
        title="Access denied",
        url="https://publisher.example/article",
        visible_text="Your request has been blocked",
        html="<p>Your request has been blocked</p>",
    )
    assert report.kind == ChallengeKind.ACCESS_DENIED


def test_ieee_unusual_traffic_page_is_access_denied():
    report = classify_access_challenge(
        title="IEEE Xplore - Unable to Load Page",
        url="https://ieeexplore.ieee.org/document/5366888/",
        visible_text=(
            "Unusual Traffic Detected (Error 418). IEEE Xplore has detected "
            "an unusual request pattern. This action has been restricted."
        ),
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


def test_inactive_recaptcha_container_on_article_is_not_a_challenge():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="Full article text",
        html=('<main>Full article text</main><div class="g-recaptcha" hidden></div>'),
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


def test_cstcloud_oauth_login_is_classified_as_sso():
    report = classify_access_challenge(
        title="中国科技云通行证登录",
        url="https://passport.escience.cn/oauth2/authorize?client_id=123",
        visible_text=(
            "登录 您正在登录 CSTCloud AAI用户服务系统 使用中国科技云通行证登录"
        ),
        html="<main>使用中国科技云通行证登录</main>",
    )
    assert report.kind == ChallengeKind.SSO


def test_carsi_institutional_login_is_classified_as_sso():
    report = classify_access_challenge(
        title="统一身份认证",
        url="https://idp.example.edu.cn/cas/login",
        visible_text="CARSI 统一身份认证 机构登录",
        html="<main>CARSI 统一身份认证</main>",
    )
    assert report.kind == ChallengeKind.SSO


def test_chinese_find_your_organization_is_classified_as_sso():
    report = classify_access_challenge(
        title="查找您的组织",
        url="https://id.publisher.example/authorization",
        visible_text="查找您的组织以访问 ScienceDirect",
        html="<main>查找您的组织</main>",
    )
    assert report.kind == ChallengeKind.SSO


def test_chinese_captcha_prompt_is_detected():
    report = classify_access_challenge(
        title="安全验证",
        url="https://publisher.example/challenge",
        visible_text="请完成人机验证后继续访问",
        html="<main>请完成人机验证后继续访问</main>",
    )
    assert report.kind == ChallengeKind.CAPTCHA


def test_chinese_article_mentioning_login_is_not_auth_prompt():
    report = classify_access_challenge(
        title="科研平台统一身份认证系统的设计",
        url="https://publisher.example/article",
        visible_text="本文研究统一身份认证系统的设计与实现。",
        html="<main>本文研究统一身份认证系统的设计与实现。</main>",
    )
    assert report.kind == ChallengeKind.NONE


def test_bare_institution_access_is_sso_handoff():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="Access through your institution",
        html="<a>Access through your institution</a>",
    )

    assert report.kind == ChallengeKind.SSO


def test_bare_organization_access_is_sso_handoff():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="Access through your organization",
        html="<a>Access through your organization</a>",
    )

    assert report.kind == ChallengeKind.SSO


def test_institution_access_prompt_with_short_instruction_is_sso_handoff():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text="Access through your institution to continue",
        html="<main>Access through your institution to continue</main>",
    )

    assert report.kind == ChallengeKind.SSO


def test_slider_captcha_is_classified():
    report = classify_access_challenge(
        title="安全验证",
        url="https://idp.example/challenge",
        visible_text="请拖动滑块完成验证",
        html="",
    )

    assert report.kind == ChallengeKind.CAPTCHA


def test_authenticator_push_is_classified_as_mfa():
    report = classify_access_challenge(
        title="Verify your identity",
        url="https://login.example/mfa",
        visible_text="Approve the sign-in request in your Authenticator app",
        html="",
    )

    assert report.kind == ChallengeKind.MFA


def test_article_page_with_institution_link_is_not_false_sso():
    report = classify_access_challenge(
        title="Target Article",
        url="https://publisher.example/article",
        visible_text=(
            "Target Article Abstract Introduction Results "
            "Access through your institution References"
        ),
        html="<main>Full article content is visible</main>",
    )

    assert report.kind == ChallengeKind.NONE


def test_long_institution_chooser_page_is_sso():
    report = classify_access_challenge(
        title="Choose your institution",
        url="https://publisher.example/institution-access",
        visible_text=(
            "Choose your institution "
            + "Search universities and research organizations. " * 20
        ),
        html="",
    )

    assert report.kind == ChallengeKind.SSO


def test_challenge_classifier_ignores_far_tail_article_text():
    report = classify_access_challenge(
        title="Readable Article",
        url="https://publisher.example/article",
        visible_text=("normal article text " * 10_000) + " please sign in",
        html="<main>Readable article</main>",
    )

    assert report.kind == ChallengeKind.NONE


def test_live_sciencedirect_turnstile_challenge_is_classified():
    report = classify_access_challenge(
        title="请稍候…",
        url="https://www.sciencedirect.com/science/article/pii/example",
        visible_text=(
            "Are you a robot? Please confirm you are a human by completing "
            "the captcha challenge below."
        ),
        html=(
            '<iframe src="https://challenges.cloudflare.com/cdn-cgi/'
            'challenge-platform/h/g/turnstile/f/av0/example"></iframe>'
        ),
    )

    assert report.kind == ChallengeKind.CAPTCHA
