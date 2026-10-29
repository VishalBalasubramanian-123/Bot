from assistant.config import QDRANT_COLLECTION_NAME
from qdrant_client import models
from assistant.db import get_client

def resolve_sender(name: str) -> list[str]:
    """Return the stored sender strings ("Name <addr>") whose name or address contains `name`. See docs/FUNCTIONS.md."""

    senders = set()
    offset = None

    # scroll returns one page of chunks at a time, so keep going until there is no next page
    while True:
        points, offset = get_client().scroll(
            collection_name=QDRANT_COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="sender", match=models.MatchText(text=name))]
            ),
            with_payload=["sender"],
            with_vectors=False,
            limit=256,
            offset=offset,
        )
        for point in points:
            senders.add(point.payload["sender"])
        if offset is None:
            break

    return sorted(senders)
