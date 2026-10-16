from assistant.config import QDRANT_COLLECTION_NAME, QDRANT_LOCAL_PATH
from qdrant_client import QdrantClient, models
import atexit
from assistant.ingest.embeddings import embed_query
import assistant.filters as filters

client = QdrantClient(path=QDRANT_LOCAL_PATH)
atexit.register(client.close) 

def hybrid_search(query, filters=None):
    """This is a common search function for the connected external systems to do search on their contents. Gmauil, Drive, Calendar uses this."""

    # This is for searching and combining query results
    embeddings = embed_query(query)
    dense_vector, sparse_vec = next(embeddings)
    indices, values = sparse_vec

    search_results = client.query_points(
        collection_name=QDRANT_COLLECTION_NAME,
        prefetch=[
            models.Prefetch(
                query=dense_vector,
                using="dense",
                limit=20,
            ),
            models.Prefetch(
            
                query=models.SparseVector(indices=indices, values=values),
                using="sparse",
                limit=20,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),  # Qdrant does RRF for you
        limit=5,
        with_payload=True,
    )

    # filter by sender, date range, label, source, etc.
    build_filters = filters._build_final_filter(**filters)
    query_filter = client.query_points(

    )

    return search_results



