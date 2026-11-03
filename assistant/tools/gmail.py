import base64
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from assistant.auth import build_service, execute
from assistant.config import USER_TIMEZONE
from assistant.ingest.gmail_parse import message_fields
from assistant.recipients import resolve_sender
from assistant.search import hybrid_search
from assistant.tools.errors import ToolError

_gmail_service = None


def _gmail():
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = build_service("gmail", "v1")
    return _gmail_service

def gmail_search(query, sender=None, date_from=None, date_to=None) -> list[dict]:
    """Search the user's indexed Gmail and return the matching emails, best match first. See docs/FUNCTIONS.md."""

    if not query:
        raise ToolError("query is empty. Pass the topic to search for, e.g. query='invoice'.")

    filters = {}

    if date_from or date_to:
        filters["date_range"], filters["intent"] = _date_filter(date_from, date_to)

    # Claude puts the person's name in `sender`; turn it into the sender strings stored in the index
    if sender:
        senders = resolve_sender(sender)
        if not senders:
            raise ToolError(f"No sender matching '{sender}'. Try the full name or the email address, or search without sender.")
        filters["senders"] = senders

    search_results = hybrid_search(query, filters)

    # Group chunks by email; works even when chunks of one email are not next to each other
    grouped_results = defaultdict(list)
    for result in search_results:
        grouped_results[result["payload"]["external_id"]].append(result["payload"])

    # Dicts keep insertion order, so emails stay sorted by their best chunk's score
    return [_to_email(chunks) for chunks in grouped_results.values()]


def get_thread(thread_id: str) -> list[dict]:
    """Fetch all messages in a Gmail thread, oldest first. See docs/FUNCTIONS.md."""
    thread = execute(_gmail().users().threads().get(userId="me", id=thread_id, format="full"))
    messages = sorted(thread.get("messages", []), key=lambda m: int(m["internalDate"]))
    return [_message_to_result(msg) for msg in messages]


def create_draft(external_id: str, body: str) -> dict:
    """Create a Gmail draft reply to external_id. Returns {"draft_id": ...}. See docs/FUNCTIONS.md."""
    orig = execute(_gmail().users().messages().get(userId="me", id=external_id, format="full"))
    hdrs = {h["name"].lower(): h["value"] for h in orig["payload"].get("headers", [])}
    thread_id = orig["threadId"]

    msg = MIMEText(body)
    subject = hdrs.get("subject", "")
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg["To"] = hdrs.get("reply-to") or hdrs.get("from", "")
    if hdrs.get("message-id"):
        msg["In-Reply-To"] = hdrs["message-id"]
        refs = " ".join(filter(None, [hdrs.get("references", ""), hdrs["message-id"]]))
        msg["References"] = refs

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = execute(_gmail().users().drafts().create(
        userId="me",
        body={"message": {"raw": raw, "threadId": thread_id}},
    ))
    return {"draft_id": draft["id"]}


def send_email(draft_id: str) -> dict:
    """Send a saved draft by its draft_id. Returns {"message_id": ...}. See docs/FUNCTIONS.md."""
    result = execute(_gmail().users().drafts().send(userId="me", body={"id": draft_id}))
    return {"message_id": result["id"]}


def _message_to_result(msg: dict) -> dict:
    """Convert a raw API message to the same shape as _to_email."""
    f = message_fields(msg)
    return {
        "external_id": f["external_id"],
        "thread_id":   f["thread_id"],
        "title":       f["title"],
        "sender":      f["sender"],
        "date":        f["date"],
        "participants": f["participants"],
        "text":        f["text"],
    }


def _date_filter(date_from, date_to):
    """Turn YYYY-MM-DD bounds into the (date_range, intent) pair build_filter expects; days are the user's local days."""
    day_from = _parse_day("date_from", date_from)
    day_to = _parse_day("date_to", date_to)

    start = _local_moment(day_from, time.min) if day_from else None
    # End = midnight starting the NEXT day, excluded (lt): covers the whole of date_to, even 23:59:59.5
    end = _local_moment(day_to + timedelta(days=1), time.min) if day_to else None

    if start and end:
        if day_from > day_to:
            raise ToolError(f"date_from ({date_from}) is after date_to ({date_to}).")
        return [start, end], "half_open"
    if start:
        return [start], "gte"
    return [end], "lt"


def _parse_day(name, value):
    """Parse a YYYY-MM-DD string, or raise a ToolError Claude can act on."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{name}='{value}' is not a date. Use YYYY-MM-DD, e.g. '2026-10-01'.") from None


def _local_moment(day, clock_time):
    """ISO string for that day and time in the user's timezone, with that date's offset (handles daylight saving)."""
    if USER_TIMEZONE:
        moment = datetime.combine(day, clock_time, tzinfo=ZoneInfo(USER_TIMEZONE))
    else:
        moment = datetime.combine(day, clock_time).astimezone()  # no tzinfo + astimezone() = the computer's timezone
    return moment.isoformat()


def _to_email(chunks):
    """Merge one email's chunks into a single result with only the fields Claude needs."""
    chunks = sorted(chunks, key=lambda c: c["chunk_index"])
    first = chunks[0]
    return {
        "external_id": first["external_id"],
        "thread_id": first["thread_id"],
        "title": first["title"],
        "sender": first["sender"],
        "date": first["date"],
        "participants": first["participants"],
        "parts": f"{len(chunks)} of {first['total_chunks']}",
        "text": "\n\n".join(c["chunk_text"] for c in chunks),
    }
