"""The one shared Qdrant client. Local Qdrant allows one client per folder, so every module uses get_client()."""
import atexit
from functools import lru_cache

from qdrant_client import QdrantClient

from assistant import config


@lru_cache(maxsize=1)
def get_client():
    """Open the Qdrant client on first use and return the same one after that. See docs/FUNCTIONS.md."""
    if config.QDRANT_MODE == "server":
        client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY or None)
    else:
        client = QdrantClient(path=str(config.QDRANT_LOCAL_PATH))
    atexit.register(client.close)  # close before interpreter teardown; QdrantClient.__del__ fails noisily at shutdown
    return client
