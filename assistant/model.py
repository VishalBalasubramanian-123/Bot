import random
import time
import anthropic
from assistant.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=0)

_MAX_TRIES = 5
_MAX_WAIT_SECONDS = 30  # longer than this, the user is better off being told than watching a frozen chat


class RetryLaterError(Exception):
    """The API asked us to wait longer than _MAX_WAIT_SECONDS; retry_after says how long."""

    def __init__(self, retry_after, status_code):
        self.retry_after = retry_after
        self.status_code = status_code
        reason = "rate limited" if status_code == 429 else "busy"
        super().__init__(f"The Anthropic API is {reason} (HTTP {status_code}) — try again in {retry_after:.0f}s.")


def _is_retryable(error):
    """True for errors that may pass on their own: network failures, 429 rate limits and 5xx server errors."""
    if isinstance(error, anthropic.APIConnectionError):  # includes timeouts
        return True
    if isinstance(error, anthropic.APIStatusError):
        # 429 = slow down; 5xx = server-side problem (500/502/503, 529 overloaded); other 4xx won't fix themselves
        return error.status_code == 429 or error.status_code >= 500
    return False


def _backoff(attempt):
    """Exponential backoff with full jitter: a random wait between 0 and 2**attempt seconds."""
    return random.uniform(0, 2 ** attempt)  # randomness stops many clients retrying in lockstep


def _wait_seconds(error, attempt):
    """Seconds to wait before the next try: the server's retry-after if it sent one, else exponential backoff."""
    if not isinstance(error, anthropic.APIStatusError):
        return _backoff(attempt)  # connection errors have no response, so no retry-after
    retry_after = error.response.headers.get("retry-after")
    if retry_after:
        try:
            seconds = float(retry_after)
        except ValueError:
            seconds = None  # not a number (e.g. an HTTP date) — fall back to backoff
        if seconds is not None:
            if seconds > _MAX_WAIT_SECONDS:
                raise RetryLaterError(seconds, error.status_code) from error
            return seconds  # the server's exact wait — no jitter
    return _backoff(attempt)


def call_model(messages, tools, system=""):
    for attempt in range(_MAX_TRIES):
        try:
            return client.messages.create(
                model=ANTHROPIC_MODEL,
                messages=messages,
                tools=tools,
                system=system,
                max_tokens=8192,
            )
        except anthropic.APIError as e:
            if not _is_retryable(e) or attempt == _MAX_TRIES - 1:
                raise
            time.sleep(_wait_seconds(e, attempt))