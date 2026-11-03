from datetime import date
from assistant.config import USER_TIMEZONE
from assistant.tools.registry import TOOLS

"""
The describe tool's main purpose is to load the model's requested tool details: name, description, and arguments.
At the start we do not pass all tool schemas to the model to keep context small. This scales to many tools.
loop.py passes DESCRIBE_TOOL as a tool schema; when the model calls it, loop.py dispatches to _TOOL_INDEX.
"""

DESCRIBE_TOOL = {
    "name": "describe_tool",
    "description": "Load a tool's full definition into context. Call this before using any tool for the first time.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Name of the tool to load",
            },
        },
        "required": ["tool_name"],
    },
}

_TOOL_INDEX = {t["name"]: t for t in TOOLS}


def build_system_prompt() -> str:
    """Build the system prompt with today's date injected. Call once per session."""
    today = date.today()
    tz_label = USER_TIMEZONE or "your local timezone"
    tool_names = ", ".join(_TOOL_INDEX)

    return f"""You are a personal executive assistant for Vishal.

Today is {today} ({tz_label}). Use this to resolve relative dates like "last week" or "yesterday" into YYYY-MM-DD values.

Available tools: {tool_names}

Before using any tool, call describe_tool with the tool name to load its full definition.

Rules:
- gmail_search: put only the topic in `query`. Extract sender names into `sender` and dates into `date_from`/`date_to` separately. Never put a sender name or date inside `query`.
- get_thread: before drafting a reply, call get_thread with the thread_id from search results to read the full conversation first.
- Cite every email you reference in your answer: include the sender, date, and subject.
- Only state facts about emails that come from tool results. Do not guess or invent email content.
- For send_email: always show the full draft to the user and wait for explicit confirmation before calling send_email.
- Sign off drafts as Vishal."""
