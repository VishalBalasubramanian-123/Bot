"""OAuth for Gmail/Calendar/Drive, plus the shared service builder and retry wrapper.

Run from the project root:  python -m assistant.auth
"""
import logging
import sys
import threading
import time

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from assistant import config

log = logging.getLogger(__name__)

SCOPES = config.GOOGLE_SCOPES
CREDENTIALS_PATH = config.GOOGLE_CREDENTIALS_PATH
TOKEN_PATH = config.GOOGLE_TOKEN_PATH

_RETRYABLE_403_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}

# Gmail quota units per call, as Google actually charges them (see docs/DECISIONS.md 3.10).
# The documented costs (in brackets) proved too low: a full messages.get measured ~49–62 units, not 20.
# Only messages.get is measured; the rest are the documented cost x2.5 as a cautious estimate.
_GMAIL_UNIT_COSTS = {
    "gmail.users.getProfile": 3,                  # estimated (doc 1)
    "gmail.users.history.list": 5,                # estimated (doc 2)
    "gmail.users.messages.list": 13,              # estimated (doc 5)
    "gmail.users.drafts.create": 25,              # estimated (doc 10)
    "gmail.users.messages.get": 50,               # measured  (doc 20)
    "gmail.users.messages.attachments.get": 50,   # estimated (doc 20)
    "gmail.users.threads.get": 100,               # estimated (doc 40)
    "gmail.users.drafts.send": 250,               # estimated (doc 100)
    "gmail.users.messages.send": 250,             # estimated (doc 100)
}
_DEFAULT_GMAIL_UNIT_COST = max(_GMAIL_UNIT_COSTS.values())  # unknown Gmail method: assume the most expensive


class _TokenBucket:
    """Allows on average `units_per_minute`, with bursts of at most `capacity` units."""

    def __init__(self, units_per_minute, capacity):
        self.rate = units_per_minute / 60  # units refilled per second
        self.capacity = capacity
        self.tokens = capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()  # ingestion and chat may share it later

    def acquire(self, cost):
        cost = min(cost, self.capacity)  # a call costing more than the tank would otherwise wait forever
        with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= cost:
                    self.tokens -= cost
                    return
                time.sleep((cost - self.tokens) / self.rate)


# Capacity = the most expensive single call (250): big enough that no call is under-counted,
# small enough that pacing starts within a few calls. Google enforces its per-minute limit over
# short windows, so a large burst allowance gets refused before pacing ever kicks in.
_gmail_bucket = _TokenBucket(config.GMAIL_UNITS_PER_MINUTE, max(_GMAIL_UNIT_COSTS.values()))


def _gmail_unit_cost(request):
    """Quota units this request will use; 0 for non-Gmail APIs (they have different quotas)."""
    method = getattr(request, "methodId", "") or ""
    if not method.startswith("gmail."):
        return 0
    if method not in _GMAIL_UNIT_COSTS:
        log.warning("No quota cost known for %s; assuming %d units", method, _DEFAULT_GMAIL_UNIT_COST)
        return _DEFAULT_GMAIL_UNIT_COST
    return _GMAIL_UNIT_COSTS[method]


def get_credentials():
    creds = None

    # 1. Do we already have a saved token from a previous run?
    if TOKEN_PATH.exists():
        log.info("Loading saved token from %s", TOKEN_PATH)
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        missing = set(SCOPES) - set(creds.scopes or [])
        if missing:
            log.warning("Saved token lacks scopes %s; re-running consent.", sorted(missing))
            creds = None

    # 2. Is it missing, expired, or invalid?
    if creds and creds.valid:
        log.info("Saved token is valid; no consent needed.")
        return creds

    if creds and creds.expired and creds.refresh_token:
        log.info("Token expired; refreshing silently.")
        try:
            creds.refresh(Request())
        except RefreshError as e:
            log.warning("Refresh failed (%s); falling back to browser consent.", e)
            creds = None

    if not creds or not creds.valid:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"OAuth client secrets not found at {CREDENTIALS_PATH}. "
                "Download the Desktop-app client JSON from Google Cloud Console."
            )
        log.info("Starting OAuth consent flow in your browser...")
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

    # 3. Save it so next run skips the browser entirely
    TOKEN_PATH.write_text(creds.to_json())
    log.info("Token saved to %s", TOKEN_PATH)
    return creds


def build_service(api, version):
    """e.g. build_service("gmail", "v1"), ("calendar", "v3"), ("drive", "v3")."""
    return build(api, version, credentials=get_credentials(), cache_discovery=False)


def _is_retryable(exc):
    if not isinstance(exc, HttpError):
        return False
    status = exc.resp.status
    if status == 429 or status >= 500:
        return True
    if status == 403:
        reasons = {d.get("reason") for d in (exc.error_details or []) if isinstance(d, dict)}
        return bool(reasons & _RETRYABLE_403_REASONS)
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential_jitter(initial=1, max=60),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def execute(request):
    """Run a googleapiclient request: paced by the Gmail unit budget, backing off on 429 / quota 403 / 5xx."""
    cost = _gmail_unit_cost(request)
    if cost:
        _gmail_bucket.acquire(cost)  # inside the retried body, so every retry is paced too
    return request.execute()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        creds = get_credentials()
    except Exception:
        log.exception("OAuth setup failed")
        sys.exit(1)
    log.info("Authorized scopes: %s", ", ".join(creds.scopes or SCOPES))
