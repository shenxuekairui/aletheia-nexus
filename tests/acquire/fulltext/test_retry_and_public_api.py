import pytest

import aletheia_nexus.acquire.fulltext as fulltext
from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionNetworkError,
    AcquisitionRequestError,
)
from aletheia_nexus.acquire.fulltext.retry import (
    AcquisitionRetryError,
    call_with_retry,
)


def test_public_api_exports_direct_acquisition_surface():
    assert callable(fulltext.acquire_direct_pdf)
    assert fulltext.AcquisitionStatus.VERIFIED.value == "VERIFIED"
    assert fulltext.IdentityStatus.UNKNOWN.value == "UNKNOWN"
    assert fulltext.DocumentRole.SUPPLEMENT.value == "SUPPLEMENT"


def test_transient_network_error_is_retried():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AcquisitionNetworkError("temporary")
        return "ok"

    value, attempts, _ = call_with_retry(
        operation,
        max_attempts=3,
        backoff_base=0,
    )

    assert value == "ok"
    assert attempts == 2


def test_permanent_request_error_is_not_retried():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise AcquisitionRequestError("bad request")

    with pytest.raises(AcquisitionRetryError) as caught:
        call_with_retry(operation, max_attempts=3, backoff_base=0)

    assert calls == 1
    assert caught.value.attempts == 1


def test_unknown_programming_error_propagates():
    def operation():
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError, match="bug"):
        call_with_retry(operation, max_attempts=3, backoff_base=0)
