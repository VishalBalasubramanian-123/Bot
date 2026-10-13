"""fastembed wrappers: dense (bge-small-en-v1.5, 384-d) + sparse (Qdrant/bm25). Models load lazily, once."""

from fastembed import SparseTextEmbedding, TextEmbedding
from assistant.config import EMBEDDING_MODEL, SPARSE_EMBEDDING_MODEL


model_text = TextEmbedding(model_name=EMBEDDING_MODEL)
model_sparse = SparseTextEmbedding(model_name=SPARSE_EMBEDDING_MODEL)


def embed_documents(chunks):

    dense_document = model_text.embed(documents=chunks)
    sparse_document = model_sparse.embed(documents=chunks)

    dense_list = [c.tolist() for c in dense_document]
    sparse_list = [(s.indices.tolist(), s.values.tolist()) for s in sparse_document]

    return list(zip(dense_list, sparse_list))