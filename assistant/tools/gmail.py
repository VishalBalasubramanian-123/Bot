from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from assistant.config import USER_TIMEZONE
from assistant.search import hybrid_search
from assistant.recipients import resolve_sender
from assistant.tools.errors import ToolError

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
