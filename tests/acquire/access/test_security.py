from aletheia_nexus.acquire.access.security import redact_url_for_record


def test_redact_url_preserves_route_shape_but_not_values():
    value = redact_url_for_record(
        "https://cdn.example/paper.pdf?token=secret&download=true#viewer"
    )
    assert value == (
        "https://cdn.example/paper.pdf?token=%5Bredacted%5D&download=%5Bredacted%5D"
    )
    assert "secret" not in value
    assert "true" not in value
    assert "#viewer" not in value


def test_redact_url_without_query_is_unchanged_except_fragment():
    assert (
        redact_url_for_record("https://publisher.example/article#section")
        == "https://publisher.example/article"
    )


def test_redact_url_accepts_none():
    assert redact_url_for_record(None) is None
