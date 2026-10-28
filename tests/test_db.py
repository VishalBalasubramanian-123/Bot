import importlib
import pytest
from unittest.mock import patch
from assistant import db


@pytest.fixture(autouse=True)
def fresh_cache():
    db.get_client.cache_clear()
    yield
    db.get_client.cache_clear()


@patch("assistant.db.QdrantClient")
def test_get_client_returns_same_instance(mock_qdrant):
    first = db.get_client()
    second = db.get_client()
    assert first is second
    assert mock_qdrant.call_count == 1


@patch("assistant.db.QdrantClient")
def test_get_client_local_mode_uses_path(mock_qdrant):
    with patch.object(db.config, "QDRANT_MODE", "local"):
        db.get_client()
    assert "path" in mock_qdrant.call_args.kwargs


@patch("assistant.db.QdrantClient")
def test_get_client_server_mode_uses_url(mock_qdrant):
    with patch.object(db.config, "QDRANT_MODE", "server"), \
         patch.object(db.config, "QDRANT_URL", "http://localhost:6333"):
        db.get_client()
    assert mock_qdrant.call_args.kwargs["url"] == "http://localhost:6333"


@patch("assistant.db.QdrantClient")
def test_importing_modules_opens_no_client(mock_qdrant):
    # Importing (or re-importing) search, recipients and index must not touch Qdrant
    import assistant.search, assistant.recipients, assistant.ingest.index
    for module in (assistant.search, assistant.recipients, assistant.ingest.index):
        importlib.reload(module)
    assert mock_qdrant.call_count == 0
