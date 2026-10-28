import httpx
import anthropic
import pytest
from unittest.mock import patch
from assistant import model
from assistant.model import call_model, RetryLaterError, _is_retryable, _wait_seconds, _backoff

_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(status_code, retry_after=None):
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(status_code, headers=headers, request=_REQUEST)
    error_class = {
        400: anthropic.BadRequestError,
        401: anthropic.AuthenticationError,
        429: anthropic.RateLimitError,
    }.get(status_code, anthropic.InternalServerError if status_code >= 500 else anthropic.APIStatusError)
    return error_class("boom", response=response, body=None)


def _waits(mock_sleep):
    return [c.args[0] for c in mock_sleep.call_args_list]


# ── _is_retryable ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 529])
def test_retryable_status_codes(status_code):
    assert _is_retryable(_status_error(status_code)) is True


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_client_errors_not_retryable(status_code):
    assert _is_retryable(_status_error(status_code)) is False


def test_connection_error_and_timeout_retryable():
    assert _is_retryable(anthropic.APIConnectionError(request=_REQUEST)) is True
    assert _is_retryable(anthropic.APITimeoutError(request=_REQUEST)) is True


# ── _backoff / _wait_seconds ──────────────────────────────────────────────────

@pytest.mark.parametrize("attempt", [0, 1, 2, 3])
def test_backoff_stays_within_range(attempt):
    waits = [_backoff(attempt) for _ in range(1000)]
    assert all(0 <= w <= 2 ** attempt for w in waits)


def test_backoff_is_random():
    # Jitter: repeated waits for the same attempt shouldn't all be identical
    assert len({_backoff(3) for _ in range(20)}) > 1


def test_wait_uses_retry_after_exactly():
    assert _wait_seconds(_status_error(429, retry_after="10"), attempt=0) == 10.0


def test_wait_accepts_fractional_retry_after():
    assert _wait_seconds(_status_error(429, retry_after="0.5"), attempt=0) == 0.5


def test_wait_falls_back_to_backoff_without_header():
    assert 0 <= _wait_seconds(_status_error(503), attempt=2) <= 4


def test_wait_falls_back_to_backoff_when_retry_after_is_a_date():
    error = _status_error(429, retry_after="Wed, 21 Oct 2026 07:28:00 GMT")
    assert 0 <= _wait_seconds(error, attempt=1) <= 2


def test_wait_falls_back_to_backoff_for_connection_error():
    assert 0 <= _wait_seconds(anthropic.APIConnectionError(request=_REQUEST), attempt=1) <= 2


def test_wait_at_cap_is_allowed():
    assert _wait_seconds(_status_error(429, retry_after="30"), attempt=0) == 30.0


def test_wait_over_cap_raises_retry_later():
    with pytest.raises(RetryLaterError) as exc:
        _wait_seconds(_status_error(429, retry_after="45"), attempt=0)
    assert exc.value.retry_after == 45.0
    assert exc.value.status_code == 429
    assert "rate limited" in str(exc.value) and "45s" in str(exc.value)


def test_retry_later_message_for_overloaded():
    with pytest.raises(RetryLaterError) as exc:
        _wait_seconds(_status_error(529, retry_after="120"), attempt=0)
    assert "busy" in str(exc.value) and "120s" in str(exc.value)


# ── call_model ────────────────────────────────────────────────────────────────

@patch("assistant.model.time.sleep")
@patch.object(model.client.messages, "create")
def test_call_model_returns_response_first_try(mock_create, mock_sleep):
    mock_create.return_value = "OK"
    assert call_model([], []) == "OK"
    assert mock_create.call_count == 1
    mock_sleep.assert_not_called()


@patch("assistant.model.time.sleep")
@patch.object(model.client.messages, "create")
def test_call_model_retries_server_errors(mock_create, mock_sleep):
    mock_create.side_effect = [_status_error(503), _status_error(500), "OK"]
    assert call_model([], []) == "OK"
    assert mock_create.call_count == 3
    assert len(_waits(mock_sleep)) == 2


@patch("assistant.model.time.sleep")
@patch.object(model.client.messages, "create")
def test_call_model_waits_retry_after_on_rate_limit(mock_create, mock_sleep):
    mock_create.side_effect = [_status_error(429, retry_after="10"), "OK"]
    assert call_model([], []) == "OK"
    assert _waits(mock_sleep) == [10.0]


@patch("assistant.model.time.sleep")
@patch.object(model.client.messages, "create")
def test_call_model_retries_connection_errors(mock_create, mock_sleep):
    mock_create.side_effect = [anthropic.APITimeoutError(request=_REQUEST), "OK"]
    assert call_model([], []) == "OK"
    assert mock_create.call_count == 2


@pytest.mark.parametrize("status_code", [400, 401])
@patch("assistant.model.time.sleep")
@patch.object(model.client.messages, "create")
def test_call_model_does_not_retry_client_errors(mock_create, mock_sleep, status_code):
    mock_create.side_effect = [_status_error(status_code), "OK"]
    with pytest.raises(anthropic.APIStatusError):
        call_model([], [])
    assert mock_create.call_count == 1
    mock_sleep.assert_not_called()


@patch("assistant.model.time.sleep")
@patch.object(model.client.messages, "create")
def test_call_model_gives_up_after_max_tries(mock_create, mock_sleep):
    mock_create.side_effect = [_status_error(503)] * model._MAX_TRIES
    with pytest.raises(anthropic.InternalServerError):
        call_model([], [])
    assert mock_create.call_count == model._MAX_TRIES
    assert len(_waits(mock_sleep)) == model._MAX_TRIES - 1  # no wait after the last try


@patch("assistant.model.time.sleep")
@patch.object(model.client.messages, "create")
def test_call_model_stops_immediately_on_long_retry_after(mock_create, mock_sleep):
    mock_create.side_effect = [_status_error(429, retry_after="45"), "OK"]
    with pytest.raises(RetryLaterError):
        call_model([], [])
    assert mock_create.call_count == 1
    mock_sleep.assert_not_called()
