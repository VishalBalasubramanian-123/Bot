from assistant.config import QDRANT_COLLECTION_NAME
from qdrant_client import models
from assistant.db import get_client
from assistant.ingest.embeddings import embed_query
from assistant.utils.filters import FilterBuilder

def hybrid_search(query, filters=None):
    """This is a common search function for the connected external systems to do search on their contents. Gmauil, Drive, Calendar uses this."""

    # This is for searching and combining query results
    embeddings = embed_query(query)
    dense_vector, sparse_vec = next(embeddings)
    indices, values = sparse_vec

    filter_build = build_filter(**filters) if filters else None

    search_results = get_client().query_points(
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
        query_filter=filter_build,
        limit=5,
        with_payload=True,
    )

    result = [
        {
            "id": point.id,
            "score": point.score,
            "payload": point.payload
        }
        for point in search_results.points
    ]
    return result

def build_filter(senders=None, participants=None, labels=None, date_range=None, intent="range", source=None):
    return (
        FilterBuilder()
        .add_senders(senders)
        .add_participants(participants)
        .add_labels(labels)
        .add_date_range(date_range, intent)
        .add_source(source)
        .build()
    )