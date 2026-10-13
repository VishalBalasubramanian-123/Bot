"""The one Qdrant collection: client, collection setup, shared payload schema, dedup + upsert.

Every source (gmail / calendar / drive) goes through upsert_document(), so all
points carry the same payload fields.
"""
import atexit
import logging
import uuid
from dataclasses import dataclass, field
from collections import defaultdict

from qdrant_client import QdrantClient, models

from assistant import config
from assistant.ingest.chunking import chunk_text, content_hash
from assistant.ingest.embeddings import embed_documents

log = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "sparse"
SOURCES = ("gmail", "calendar", "drive")
_ID_NAMESPACE = uuid.UUID("5b1c9c0e-3f7a-4d8e-9a55-2f0f6f3f2a10")
_ID_BATCH_SIZE = 500


@dataclass
class Document:
    """One email / event / file, before chunking. `title` holds subject, event title, or file name."""
    source: str
    external_id: str
    title: str
    text: str
    date: str | None = None
    sender: str | None = None
    participants: list[str] = field(default_factory=list)
    thread_id: str | None = None # Gmail only
    mime_type: str | None = None       # Drive only
    metadata_only: bool = False

@dataclass
class chunks:
    """One chunk of a Document, ready to embed and upsert into Qdrant."""
    document: Document
    chunk_index: int
    total_chunks: int
    chunk_text: str
    content_hash: str
    ingested_at: str

client = QdrantClient(path=config.QDRANT_LOCAL_PATH)
atexit.register(client.close)  # close before interpreter teardown; QdrantClient.__del__ fails noisily at shutdown

if not client.collection_exists(config.QDRANT_COLLECTION_NAME):
    client.create_collection(
        collection_name=config.QDRANT_COLLECTION_NAME,
        vectors_config={
            DENSE: models.VectorParams(size=config.EMBEDDING_DIM, distance=models.Distance.COSINE),
        },
        sparse_vectors_config={
            SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF),
        },
    )
def upsert_document(document, known_hashes):
    """Store one Document; returns points written. See docs/FUNCTIONS.md."""

    chunks = chunk_text(document.text)

    if not chunks:
        return 0

    total_chunks = len(chunks)

    hash_val = [content_hash(chunk) for chunk in chunks]

    if known_hashes and set(hash_val) == known_hashes:
        return 0

    chunk_title = [ f"{document.title}\n\n{chunk}" for chunk in chunks] # adds the title along with the chunk for embeddings
    embed = embed_documents(chunk_title)

    if known_hashes:
        client.delete(
        collection_name=config.QDRANT_COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(must=[
                models.FieldCondition(key="source", match=models.MatchValue(value=document.source)),
                models.FieldCondition(key="external_id", match=models.MatchValue(value=document.external_id)),
            ])
        ),
    )

    points = []
    for chunk_index, chunk in enumerate(chunks):
        id = uuid.uuid5(_ID_NAMESPACE, f"{document.source}:{document.external_id}:{chunk_index}")
        dense, sparse = embed[chunk_index]
        indices, values = sparse
        points.append(models.PointStruct(
            id=id,
            vector={DENSE: dense, SPARSE:  models.SparseVector(indices=indices, values=values)},
            payload={
            "source": document.source, 
            "external_id": document.external_id, 
            "thread_id": document.thread_id, 
            "title": document.title, 
            "sender": document.sender, 
            "participants": document.participants, 
            "date": document.date,
            "chunk_index": chunk_index, 
            "total_chunks": total_chunks, 
            "chunk_text": chunk, 
            "content_hash": hash_val[chunk_index]
        },
        ))

    client.upsert(collection_name=config.QDRANT_COLLECTION_NAME, points=points)
    return len(points)

def existing_hashes_ids(source, ids):
    """{external_id: {content_hash, ...}} for the stored items among ids. See docs/FUNCTIONS.md."""

    if not ids:
        return {}
    
    stored = defaultdict(set)

    for id in range(0, len(ids), _ID_BATCH_SIZE):
        offset = None
        batch = ids[id: id + _ID_BATCH_SIZE]
        while True:
            results, next_page_offset = client.scroll(
                collection_name=config.QDRANT_COLLECTION_NAME,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(key="external_id", match=models.MatchAny(any=batch)),
                        models.FieldCondition(key="source", match=models.MatchValue(value=source))
                    ]
                ),
                with_payload=["external_id", "content_hash"],
                with_vectors=False,
                limit=100,          # Number of points per page
                offset=offset,
            )
            
            for i in results:
                stored[i.payload["external_id"]].add(i.payload["content_hash"])
            
            if next_page_offset is None:
                break

            offset = next_page_offset

    return dict(stored)