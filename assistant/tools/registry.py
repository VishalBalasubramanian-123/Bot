from assistant.tools.gmail import gmail_search, get_thread, create_draft, send_email
from assistant.tools.errors import ToolError


TOOLS = [
    {
        "name": "gmail_search",
        "description": "Semantic search over the user's indexed Gmail. Put only the topic in `query` — not the full user question. "
        "Extract sender names into `sender` and dates into `date_from`/`date_to` separately.",
        "input_schema": {    
            "type": "object",
            "properties": {
                "query": { 
                    "type": "string",
                    "description": "The topic or subject to search for, e.g. 'invoice', 'meeting rescheduled', 'contract'. Topic only — do not include sender names or dates here.",
                },
                "sender": {
                    "type": "string",
                    "description": "Name or company to filter by, e.g. 'AWS', 'Priya', 'Google'. Extract from the user's question. Omit if no sender was mentioned.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date as YYYY-MM-DD, inclusive. Use today's date as a reference for relative terms like 'last week'.",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date as YYYY-MM-DD, inclusive.",              
                },

            },
            "required": ["query"],
        },
    },
    {
        "name": "get_thread",
        "description": (
            "Fetch all messages in a Gmail thread in chronological order. "
            "Use this when you need the full conversation before drafting a reply. "
            "Pass the thread_id from gmail_search results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "The thread_id from gmail_search results.",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "create_draft",
        "description": (
            "Create a draft reply to an email in Gmail. "
            "Use the external_id from gmail_search results to identify which email to reply to. "
            "Returns a draft_id that can be passed to send_email once the user approves."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "external_id": {
                    "type": "string",
                    "description": "The external_id of the email to reply to, from gmail_search results.",
                },
                "body": {
                    "type": "string",
                    "description": "The full text of the reply.",
                },
            },
            "required": ["external_id", "body"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Send a draft email. Only call this after the user has explicitly confirmed they want to send. "
            "Pass the draft_id returned by create_draft."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "The draft_id returned by create_draft.",
                },
            },
            "required": ["draft_id"],
        },
    },
]


_DISPATCH = {
    "gmail_search": gmail_search,
    "get_thread":   get_thread,
    "create_draft": create_draft,
    "send_email":send_email
}

def dispatch(name, args):
    tool = _DISPATCH.get(name)
    if tool is None:
        raise ToolError(f"Unknown tool '{name}'.")
    return tool(**args)