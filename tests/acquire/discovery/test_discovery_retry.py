import pytest

import aletheia_nexus.acquire.discovery.retry as retry_module
from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryNetworkError,
    DiscoveryParseError,
)
from aletheia_nexus.acquire.discovery.retry import (
    RetryCallError,
    call_with_retry,
    validate_retry_config,
)


def test_call_with_retry_recovers_from_temporary_failures(monkeypatch):
    calls = 0
    delays = []

    def flaky_call():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise DiscoveryNetworkError("temporary network failure")
        return "ok"

    monkeypatch.setattr(retry_module.time, "sleep", delays.append)

    value, attempts, elapsed_seconds = call_with_retry(
        flaky_call,
        max_attempts=3,
        backoff_base=0.25,
    )

    assert value == "ok"
    assert attempts == 3
    assert elapsed_seconds >= 0
    assert calls == 3
    assert delays == [0.25, 0.5]


def test_call_with_retry_does_not_retry_permanent_discovery_error(monkeypatch):
    calls = 0
    delays = []

    def bad_payload():
        nonlocal calls
        calls += 1
        raise DiscoveryParseError("malformed response")

    monkeypatch.setattr(retry_module.time, "sleep", delays.append)

    with pytest.raises(RetryCallError) as exc_info:
        call_with_retry(
            bad_payload,
            max_attempts=5,
            backoff_base=1.0,
        )

    assert isinstance(exc_info.value.error, DiscoveryParseError)
    assert exc_info.value.attempts == 1
    assert exc_info.value.elapsed_seconds >= 0
    assert calls == 1
    assert delays == []


def test_call_with_retry_does_not_swallow_programming_errors():
    def broken_call():
        raise ValueError("programming bug")

    with pytest.raises(ValueError, match="programming bug"):
        call_with_retry(broken_call)


@pytest.mark.parametrize(
    ("max_attempts", "backoff_base", "exception_type"),
    [
        (0, 1.0, ValueError),
        (True, 1.0, TypeError),
        (3, -1.0, ValueError),
        (3, float("inf"), ValueError),
        (3, True, TypeError),
    ],
)
def test_validate_retry_config_rejects_invalid_values(
    max_attempts,
    backoff_base,
    exception_type,
):
    with pytest.raises(exception_type):
        validate_retry_config(max_attempts, backoff_base)
