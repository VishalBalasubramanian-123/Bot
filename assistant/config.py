"""Single place that reads .env. Every other module imports settings from here."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _str(name, default=None):
    value = os.getenv(name, "").strip()
    if value:
        return value
    if default is None:
        raise RuntimeError(f"Missing required setting {name} in .env")
    return default


def _int(name, default=None):
    return int(_str(name, None if default is None else str(default)))


def _float(name, default=None):
    return float(_str(name, None if default is None else str(default)))


def _bool(name, default=None):
    return _str(name, None if default is None else str(default)).lower() in ("1", "true", "yes")


def _list(name, default=None):
    return [item.strip() for item in _str(name, default).split(",") if item.strip()]


def _path(name, default=None):
    path = Path(_str(name, default))
    return path if path.is_absolute() else PROJECT_ROOT / path


# ── Model ────────────────────────────────────────────────────
# Optional here so ingestion runs without it; model.py should fail loudly if empty.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = _str("ANTHROPIC_MODEL", "claude-sonnet-5")
TURN_CEILING = _int("TURN_CEILING", 18)

# ── Google OAuth ─────────────────────────────────────────────
GOOGLE_CREDENTIALS_PATH = _path("GOOGLE_CREDENTIALS_PATH", "credentials.json")
GOOGLE_TOKEN_PATH = _path("GOOGLE_TOKEN_PATH", "token.json")
GMAIL_SCOPES = _list("GMAIL_SCOPES")
CALENDAR_SCOPES = _list("CALENDAR_SCOPES")
DRIVE_SCOPES = _list("DRIVE_SCOPES")
GOOGLE_SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES + DRIVE_SCOPES
GMAIL_UNITS_PER_MINUTE = _int("GMAIL_UNITS_PER_MINUTE", 4800)  # Google's per-user limit is 6,000; stay below it

# ── Qdrant ───────────────────────────────────────────────────
QDRANT_MODE = _str("QDRANT_MODE", "local")
QDRANT_LOCAL_PATH = _path("QDRANT_LOCAL_PATH", "data/qdrant")
QDRANT_COLLECTION_NAME = _str("QDRANT_COLLECTION_NAME", "exec_assistant_v1")
QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "").strip()

# ── Embeddings ───────────────────────────────────────────────
EMBEDDING_PROVIDER = _str("EMBEDDING_PROVIDER", "fastembed")
EMBEDDING_MODEL = _str("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
FINAL_NAME = QDRANT_COLLECTION_NAME + "__" + EMBEDDING_MODEL.split("/")[-1]
QDRANT_COLLECTION_NAME = FINAL_NAME
EMBEDDING_DIM = _int("EMBEDDING_DIM", 384)
SPARSE_EMBEDDING_MODEL = _str("SPARSE_EMBEDDING_MODEL", "Qdrant/bm25")
HYBRID_FUSION_METHOD = _str("HYBRID_FUSION_METHOD", "rrf")

# ── Ingestion ────────────────────────────────────────────────
INGEST_INTERVAL_MINUTES = _int("INGEST_INTERVAL_MINUTES", 5)
INGEST_LOOKBACK_DAYS = _int("INGEST_LOOKBACK_DAYS", 30)
CHUNK_SIZE_TOKENS = _int("CHUNK_SIZE_TOKENS", 400)
CHUNK_OVERLAP_TOKENS = _int("CHUNK_OVERLAP_TOKENS", 50)

# ── Storage bounding ─────────────────────────────────────────
DRIVE_MAX_TEXT_EXTRACT_MB = _float("DRIVE_MAX_TEXT_EXTRACT_MB", 10)
DRIVE_SKIP_MIME_TYPES = _list("DRIVE_SKIP_MIME_TYPES", "video/*,application/zip,application/octet-stream")
INDEX_MAX_SIZE_GB = _float("INDEX_MAX_SIZE_GB", 5)
INDEX_RETENTION_DAYS = _int("INDEX_RETENTION_DAYS", 365)

# ── Context / durability / guardrails ────────────────────────
CONTEXT_TOKEN_BUDGET = _int("CONTEXT_TOKEN_BUDGET", 50000)
CONTEXT_COMPACT_THRESHOLD = _float("CONTEXT_COMPACT_THRESHOLD", 0.75)
MEMORY_FILE_PATH = _path("MEMORY_FILE_PATH", "assistant/memory.md")
EVENT_LOG_PATH = _path("EVENT_LOG_PATH", "data/event_log.jsonl")
PRESIDIO_ENABLED = _bool("PRESIDIO_ENABLED", False)
GROUNDING_CHECK_ENABLED = _bool("GROUNDING_CHECK_ENABLED", False)

# ── Dev safety ───────────────────────────────────────────────
APP_ENV = _str("APP_ENV", "development")
USE_TEST_ACCOUNT = _bool("USE_TEST_ACCOUNT", True)

if EMBEDDING_PROVIDER != "fastembed":
    raise RuntimeError(f"EMBEDDING_PROVIDER must be 'fastembed', got {EMBEDDING_PROVIDER!r}")
if CHUNK_OVERLAP_TOKENS >= CHUNK_SIZE_TOKENS:
    raise RuntimeError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_SIZE_TOKENS")
