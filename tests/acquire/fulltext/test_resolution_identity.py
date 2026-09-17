from aletheia_nexus.acquire.fulltext.models import IdentityStatus
from aletheia_nexus.acquire.fulltext.resolution.identity import (
    classify_page_type,
    validate_page_identity,
)
from aletheia_nexus.acquire.fulltext.resolution.models import PageType
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html


def test_page_identity_matches_exact_doi_metadata():
    parsed = parse_html(
        '<meta name="citation_doi" content="10.1000/ABC">'
        '<meta name="citation_title" content="Target Paper">'
    )

    report = validate_page_identity(target_doi="10.1000/abc", parsed=parsed)

    assert report.status == IdentityStatus.MATCH
    assert report.doi_match is True


def test_page_identity_matches_high_title_similarity_when_doi_missing():
    parsed = parse_html(
        '<meta name="citation_title" content="Target paper: a robust route resolution study">'
    )

    report = validate_page_identity(
        target_doi="10.1000/abc",
        parsed=parsed,
        expected_title="Target paper: a robust route resolution study",
    )

    assert report.status == IdentityStatus.MATCH
    assert report.title_similarity == 1.0


def test_page_identity_rejects_explicit_different_doi():
    parsed = parse_html('<meta name="citation_doi" content="10.1000/other">')

    report = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert report.status == IdentityStatus.MISMATCH


def test_explicit_conflicting_page_doi_outweighs_title_match():
    parsed = parse_html(
        '<meta name="citation_doi" content="10.1000/other">'
        '<meta name="citation_title" content="Target Paper">'
    )

    report = validate_page_identity(
        target_doi="10.1000/target",
        parsed=parsed,
        expected_title="Target Paper",
    )

    assert report.status == IdentityStatus.MISMATCH
    assert report.title_similarity == 1.0
    assert report.doi_match is False


def test_page_identity_remains_unknown_when_evidence_is_absent():
    parsed = parse_html("<html><body>generic repository page</body></html>")

    report = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert report.status == IdentityStatus.UNKNOWN


def test_strongly_different_generic_page_title_is_not_enough_for_mismatch():
    parsed = parse_html("<title>LinkingHub</title><body>Continue to article</body>")

    report = validate_page_identity(
        target_doi="10.1000/target",
        parsed=parsed,
        expected_title="A completely different scientific article title",
    )

    assert report.status == IdentityStatus.UNKNOWN
    assert report.title_similarity is not None
    assert report.title_similarity < 0.25


def test_article_identity_takes_precedence_over_generic_sign_in_text():
    parsed = parse_html(
        '<meta name="citation_doi" content="10.1000/target">'
        "<body>Sign in to your account for saved searches</body>"
    )
    identity = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert classify_page_type(parsed, identity) == PageType.ARTICLE


def test_explicit_access_boundary_takes_precedence_over_matching_identity():
    parsed = parse_html(
        '<meta name="citation_doi" content="10.1000/target">'
        '<meta name="citation_title" content="Target Paper">'
        "<body>Access through your institution to read this article</body>"
    )
    identity = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert identity.status == IdentityStatus.MATCH
    assert classify_page_type(parsed, identity) == PageType.LOGIN


def test_weak_get_access_navigation_does_not_override_matching_identity():
    parsed = parse_html(
        '<meta name="citation_doi" content="10.1000/target">'
        "<body>Article content Get access Journal alerts</body>"
    )
    identity = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert classify_page_type(parsed, identity) == PageType.ARTICLE


def test_script_only_challenge_terms_do_not_block_article_page():
    parsed = parse_html(
        '<meta name="citation_doi" content="10.1000/target">'
        "<body>Target article</body>"
        "<script>const vendor = 'cloudflare captcha';</script>"
    )
    identity = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert classify_page_type(parsed, identity) == PageType.ARTICLE


def test_challenge_page_is_classified_without_claiming_authentication():
    parsed = parse_html("<title>Checking your browser</title>Verify you are human")
    identity = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert classify_page_type(parsed, identity) == PageType.CHALLENGE


def test_aws_waf_robot_challenge_is_classified_as_challenge():
    parsed = parse_html(
        "<html><head><title></title></head><body>"
        "<noscript><h1>JavaScript is disabled</h1>"
        "In order to continue, we need to verify that you're not a robot. "
        "This requires JavaScript. Enable JavaScript and then reload the page."
        "</noscript></body></html>"
    )
    identity = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert identity.status == IdentityStatus.UNKNOWN
    assert classify_page_type(parsed, identity) == PageType.CHALLENGE


def test_challenge_signal_takes_precedence_over_stale_article_metadata():
    parsed = parse_html(
        '<meta name="citation_doi" content="10.1000/target">'
        '<meta name="citation_title" content="Target Paper">'
        "<title>Attention Required</title>Verify you are human"
    )
    identity = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert identity.status == IdentityStatus.MATCH
    assert classify_page_type(parsed, identity) == PageType.CHALLENGE


def test_explicit_institutional_access_page_is_login():
    parsed = parse_html(
        "<title>Get access</title>Access through your institution to read this article"
    )
    identity = validate_page_identity(target_doi="10.1000/target", parsed=parsed)

    assert classify_page_type(parsed, identity) == PageType.LOGIN
