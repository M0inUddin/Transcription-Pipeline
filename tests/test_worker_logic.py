from app.core.errors import TransientProviderError
from app.services.transcription import error_info_from_exception
from app.workers.tasks import _retry_countdown


def test_retry_countdown_uses_capped_exponential_backoff() -> None:
    assert _retry_countdown(15, 0) == 15
    assert _retry_countdown(15, 2) == 60
    assert _retry_countdown(15, 8) == 300


def test_error_info_marks_transient_provider_errors_retryable() -> None:
    error = error_info_from_exception(TransientProviderError("rate limited", status_code=429))

    assert error.code == "transient_provider_error"
    assert error.retryable is True
    assert error.provider_status_code == 429

