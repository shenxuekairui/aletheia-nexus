from io import BytesIO

import httpx
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import elsevier
from aletheia_nexus.acquire.access.models import (
    ElsevierAccessConfig,
    ElsevierAccessStatus,
)


def _pdf_bytes(title: str) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title})
    writer.write(output)
    return output.getvalue()


def _install_transport(monkeypatch, handler):
    real_client = httpx.Client
    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(elsevier.httpx, "Client", client_factory)
    monkeypatch.setattr(elsevier, "validate_safe_url", lambda value: value)


def test_elsevier_config_repr_hides_all_secret_values():
    config = ElsevierAccessConfig(
        api_key="api-secret",
        inst_token="institution-secret",
        bearer_token="bearer-secret",
    )
    rendered = repr(config)
    assert "api-secret" not in rendered
    assert "institution-secret" not in rendered
    assert "bearer-secret" not in rendered


def test_elsevier_official_pdf_is_scientifically_validated(monkeypatch, tmp_path):
    seen_headers = {}

    def handler(request):
        seen_headers.update(request.headers)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=_pdf_bytes("Official Elsevier Article"),
        )

    _install_transport(monkeypatch, handler)
    config = ElsevierAccessConfig(
        api_key="api-secret",
        inst_token="institution-secret",
    )

    attempt = elsevier.acquire_elsevier_pdf(
        "10.1016/j.test.2026.100001",
        config=config,
        output_dir=tmp_path,
        expected_title="Official Elsevier Article",
    )

    assert attempt.status == ElsevierAccessStatus.VERIFIED
    assert attempt.result is not None
    assert attempt.result.file_path is not None
    assert seen_headers["x-els-apikey"] == "api-secret"
    assert seen_headers["x-els-insttoken"] == "institution-secret"
    assert seen_headers["accept"] == "application/pdf"

    sidecar = attempt.result.sidecar_path.read_text(encoding="utf-8").lower()
    assert "api-secret" not in sidecar
    assert "institution-secret" not in sidecar
    assert "elsevier_article_retrieval_api" in sidecar


def test_elsevier_entitlement_failure_is_explicit(monkeypatch, tmp_path):
    def handler(request):
        return httpx.Response(
            403,
            content=b"Requester is not entitled to this subscription content",
        )

    _install_transport(monkeypatch, handler)
    attempt = elsevier.acquire_elsevier_pdf(
        "10.1016/j.test.2026.100002",
        config=ElsevierAccessConfig(api_key="api-secret"),
        output_dir=tmp_path,
    )

    assert attempt.status == ElsevierAccessStatus.ENTITLEMENT_REQUIRED
    assert attempt.http_status == 403


def test_elsevier_rate_limit_is_explicit(monkeypatch, tmp_path):
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(429, content=b"quota exceeded"),
    )

    attempt = elsevier.acquire_elsevier_pdf(
        "10.1016/j.test.2026.100003",
        config=ElsevierAccessConfig(api_key="api-secret"),
        output_dir=tmp_path,
    )

    assert attempt.status == ElsevierAccessStatus.RATE_LIMITED


def test_elsevier_redirect_target_is_validated_before_follow(monkeypatch, tmp_path):
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/private.pdf"},
        )
    )

    monkeypatch.setattr(
        elsevier.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    def safety(value):
        if "127.0.0.1" in value:
            raise ValueError("local target")
        return value

    monkeypatch.setattr(elsevier, "validate_safe_url", safety)

    attempt = elsevier.acquire_elsevier_pdf(
        "10.1016/j.test.2026.100004",
        config=ElsevierAccessConfig(api_key="api-secret"),
        output_dir=tmp_path,
    )

    assert attempt.status == ElsevierAccessStatus.ERROR
    assert attempt.error == "ValueError"
    assert "127.0.0.1" not in attempt.error


def test_elsevier_credentials_are_not_forwarded_to_cross_origin_redirect(
    monkeypatch,
    tmp_path,
):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.elsevier.com":
            return httpx.Response(
                302,
                headers={"Location": "https://cdn.example/article.pdf"},
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=_pdf_bytes("Redirected Elsevier Article"),
        )

    _install_transport(monkeypatch, handler)
    config = ElsevierAccessConfig(
        api_key="api-secret",
        inst_token="institution-secret",
        bearer_token="bearer-secret",
    )

    attempt = elsevier.acquire_elsevier_pdf(
        "10.1016/j.test.2026.100005",
        config=config,
        output_dir=tmp_path,
        expected_title="Redirected Elsevier Article",
    )

    assert attempt.status == ElsevierAccessStatus.VERIFIED
    assert len(requests) == 2

    first_headers = requests[0].headers
    assert first_headers["x-els-apikey"] == "api-secret"
    assert first_headers["x-els-insttoken"] == "institution-secret"
    assert first_headers["authorization"] == "Bearer bearer-secret"

    redirected_headers = requests[1].headers
    assert "x-els-apikey" not in redirected_headers
    assert "x-els-insttoken" not in redirected_headers
    assert "authorization" not in redirected_headers
    assert redirected_headers["accept"] == "application/pdf"


def test_elsevier_author_manuscript_fallback_is_on_by_default(monkeypatch, tmp_path):
    seen_urls = []

    def handler(request):
        seen_urls.append(str(request.url))
        return httpx.Response(404, content=b"not found")

    _install_transport(monkeypatch, handler)
    elsevier.acquire_elsevier_pdf(
        "10.1016/j.test.2026.100006",
        config=ElsevierAccessConfig(api_key="api-secret"),
        output_dir=tmp_path,
    )

    assert len(seen_urls) == 1
    assert "amsRedirect=true" in seen_urls[0]


def test_elsevier_author_manuscript_fallback_can_be_disabled(monkeypatch, tmp_path):
    seen_urls = []

    def handler(request):
        seen_urls.append(str(request.url))
        return httpx.Response(404, content=b"not found")

    _install_transport(monkeypatch, handler)
    elsevier.acquire_elsevier_pdf(
        "10.1016/j.test.2026.100007",
        config=ElsevierAccessConfig(
            api_key="api-secret",
            allow_author_manuscript_fallback=False,
        ),
        output_dir=tmp_path,
    )

    assert len(seen_urls) == 1
    assert "amsRedirect" not in seen_urls[0]


def test_elsevier_config_from_env_ignores_blank_optional_tokens(monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "  api-secret  ")
    monkeypatch.setenv("ELSEVIER_INST_TOKEN", "   ")
    monkeypatch.setenv("ELSEVIER_BEARER_TOKEN", "")

    config = ElsevierAccessConfig.from_env()

    assert config is not None
    assert config.api_key == "api-secret"
    assert config.inst_token is None
    assert config.bearer_token is None


def test_elsevier_config_from_env_requires_nonblank_api_key(monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "   ")

    assert ElsevierAccessConfig.from_env() is None


def test_elsevier_error_does_not_persist_secret_url(monkeypatch, tmp_path):
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"Location": "https://cdn.example/article.pdf?token=super-secret"},
        )
    )

    monkeypatch.setattr(
        elsevier.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    def reject(value):
        if "cdn.example" in value:
            raise ValueError(
                "unsafe redirect https://cdn.example/article.pdf?token=super-secret"
            )
        return value

    monkeypatch.setattr(elsevier, "validate_safe_url", reject)

    attempt = elsevier.acquire_elsevier_pdf(
        "10.1016/j.test.2026.100008",
        config=ElsevierAccessConfig(api_key="api-secret"),
        output_dir=tmp_path,
    )

    assert attempt.status == ElsevierAccessStatus.ERROR
    assert attempt.error == "ValueError"
    assert "super-secret" not in attempt.error
    assert "cdn.example" not in attempt.error


def test_elsevier_keep_unverified_requires_boolean(tmp_path):
    try:
        elsevier.acquire_elsevier_pdf(
            "10.1016/j.test.2026.100009",
            config=ElsevierAccessConfig(
                api_key="api-secret",
                keep_unverified=1,
            ),
            output_dir=tmp_path,
        )
    except TypeError as exc:
        assert "keep_unverified" in str(exc)
    else:
        raise AssertionError("keep_unverified must require a real bool")
