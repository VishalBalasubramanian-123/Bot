"""Gmail parsing: one raw messages.get(format="full") response -> clean text + Document fields.

Pure functions, no API calls and no Qdrant, so they can be tested on sample JSON.
gmail_ingest.py does the fetching and hands the result to index.upsert_document.
"""
import base64
import re
from datetime import datetime, timezone
from email.utils import getaddresses

from bs4 import BeautifulSoup

# Where a quoted reply chain starts in a plain-text body.
_QUOTE_START = re.compile(
    r"^(On .{0,200}wrote:\s*$"                     # Gmail / Apple Mail (may wrap onto 2 lines, see below)
    r"|-{2,}\s*Original Message\s*-{2,}"           # Outlook
    r"|From: .+\n(Sent|Date): )",                  # Outlook header block
    re.MULTILINE | re.IGNORECASE,
)
# A forward's content IS the message, so it's kept — only this marker line is dropped.
_FORWARD_MARKER = re.compile(r"^.*-{2,}\s*Forwarded message\s*-{2,}.*$", re.MULTILINE | re.IGNORECASE)
_HTML_QUOTE_SELECTORS = "blockquote, div.gmail_quote, div.gmail_extra, div#appendonsend, div.yahoo_quoted, div#divRplyFwdMsg"
_HTML_BLOCK_TAGS = ["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "pre", "hr"]


def _decode(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _find_body(payload):
    """Return (mime_type, text) preferring text/plain, skipping attachments."""
    plain, html = None, None
    stack = [payload]
    while stack:
        part = stack.pop()
        stack.extend(part.get("parts", []))
        data = part.get("body", {}).get("data")
        if not data or part.get("filename"):
            continue
        if part["mimeType"] == "text/plain" and plain is None:
            plain = _decode(data)
        elif part["mimeType"] == "text/html" and html is None:
            html = _decode(data)
    if plain is not None:
        return "text/plain", plain
    if html is not None:
        return "text/html", html
    return None, ""


def clean_html(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.select("script, style, head"):
        tag.decompose()
    for tag in soup.select(_HTML_QUOTE_SELECTORS):
        if not _FORWARD_MARKER.search(tag.get_text("\n")):  # Gmail wraps forwards in div.gmail_quote too
            tag.decompose()
    # Line breaks only where the layout has them; inline tags (<b>, <a>, <span>) stay in the sentence.
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(_HTML_BLOCK_TAGS):
        block.insert_before("\n")  # text directly before a nested block ("FYI<div>Can you…") needs a break
        block.append("\n")
    return soup.get_text()


def strip_quoted(text):
    """Remove reply chains. In a forward, only the forwarder's own words get stripped;
    the forwarded part (with its From/Date/Subject lines) is kept untouched."""
    forward = _FORWARD_MARKER.search(text)
    if not forward:
        return _strip_reply_chain(text)
    own_words = _strip_reply_chain(text[:forward.start()]).strip()
    forwarded = text[forward.end():].strip()
    return f"{own_words}\n\n{forwarded}" if own_words else forwarded


def _strip_reply_chain(text):
    # Join "On <date>, <name>\n<addr> wrote:" wrapped headers so the pattern can see them.
    text = re.sub(r"^(On .{0,200})\n(.{0,200}wrote:\s*)$", r"\1 \2", text, flags=re.MULTILINE)
    match = _QUOTE_START.search(text)
    if match:
        text = text[:match.start()]
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def _normalize(text):
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_text(payload):
    mime, body = _find_body(payload)
    if mime == "text/html":
        body = clean_html(body)
    return _normalize(strip_quoted(body))


def message_fields(msg):
    """The fields of the Document for one message: index.Document(**message_fields(msg))."""
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    participants = [
        addr for _, addr in getaddresses([headers.get(k, "") for k in ("from", "to", "cc")]) if addr
    ]
    date = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc).isoformat()
    return {
        "source": "gmail",
        "external_id": msg["id"],
        "thread_id": msg["threadId"],
        "title": headers.get("subject", "(no subject)"),
        "text": extract_text(msg["payload"]) or msg.get("snippet", ""),
        "date": date,
        "sender": headers.get("from"),
        "participants": sorted(set(participants)),
    }
