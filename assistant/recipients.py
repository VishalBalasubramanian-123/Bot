from assistant.config import QDRANT_COLLECTION_NAME, QDRANT_LOCAL_PATH
from qdrant_client import QdrantClient, models
import atexit
from assistant.utils.filters import FilterBuilder

client = QdrantClient(path=QDRANT_LOCAL_PATH)
atexit.register(client.close)

def resolve_sender(name: str) -> list[str]:

    # Getting the related email id for a name
    address, _ = client.scroll(
        collection_name=QDRANT_COLLECTION_NAME,
        scroll_filter=models.Filter(
            should=[
                models.FieldCondition(key="sender", match=models.MatchText(text=name)),
                models.FieldCondition(key="participants", match=models.MatchText(text=name))
            ]
        ),
        with_payload=["sender", "participants"],
        with_vectors=False,
    )

    # Deduping
    dedup = set()
    for point in address:
        dedup.add(point.payload["sender"])
        for cand in point.payload["participants"]:
            dedup.add(cand)

    return list(dedup)
    