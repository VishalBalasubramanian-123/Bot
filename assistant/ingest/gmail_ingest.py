"""Gmail ingestion: list recent message ids -> skip already-indexed -> fetch -> parse -> upsert.

Gmail messages are immutable, so an external_id already in Qdrant means the
message is done; only unseen ids cost a messages.get call or any embedding work.

Run from the project root:  python -m assistant.ingest.gmail_ingest [--days N] [--max N]
"""
import argparse
import logging

from assistant import config
from assistant.auth import build_service, execute
from assistant.ingest.gmail_parse import message_fields
from assistant.ingest.index import Document, existing_hashes_ids, upsert_document

log = logging.getLogger(__name__)


def _list_ids(gmail, days, max_messages):
    ids, page = [], None
    query = f"newer_than:{days}d -in:drafts -in:chats"
    while True:
        resp = execute(gmail.users().messages().list(userId="me", q=query, pageToken=page, maxResults=500))
        ids.extend(m["id"] for m in resp.get("messages", []))
        page = resp.get("nextPageToken")
        if not page or (max_messages and len(ids) >= max_messages):
            return ids[:max_messages] if max_messages else ids


def run(days=None, max_messages=None):
    days = days or config.INGEST_LOOKBACK_DAYS
    gmail = build_service("gmail", "v1")

    ids = _list_ids(gmail, days, max_messages)
    seen = existing_hashes_ids("gmail", ids)
    new_ids = [i for i in ids if i not in seen]
    log.info("Gmail: %d messages in last %dd, %d already indexed, %d new", len(ids), days, len(seen), len(new_ids))

    written = failed = 0
    for n, msg_id in enumerate(new_ids, 1):
        try:
            msg = execute(gmail.users().messages().get(userId="me", id=msg_id, format="full"))
            written += upsert_document(Document(**message_fields(msg)), known_hashes=set())
        except Exception:
            failed += 1
            log.exception("Gmail: failed to ingest message %s", msg_id)
        if n % 25 == 0:
            log.info("Gmail: %d/%d processed", n, len(new_ids))

    log.info("Gmail: done — %d chunks written, %d messages failed", written, failed)
    return {"listed": len(ids), "new": len(new_ids), "chunks_written": written, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Ingest recent Gmail messages into Qdrant")
    parser.add_argument("--days", type=int, help=f"lookback window (default {config.INGEST_LOOKBACK_DAYS})")
    parser.add_argument("--max", type=int, dest="max_messages", help="cap on messages listed (for testing)")
    args = parser.parse_args()
    run(args.days, args.max_messages)
