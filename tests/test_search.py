import pytest
from unittest.mock import patch, MagicMock
from assistant.search import hybrid_search, build_filter


# ── Unit tests (mocked Qdrant) ────────────────────────────────────────────────

def _make_query_response(n=3):
    response = MagicMock()
    response.points = [
        MagicMock(
            id=f"id-{i}",
            score=1.0 - i * 0.1,
            payload={
                "sender": f"sender{i}@example.com",
                "title": f"Subject {i}",
                "date": "2026-10-10T00:00:00+00:00",
                "external_id": f"gmail-id-{i}",
                "chunk_text": f"some email content {i}",
                "chunk_index": 0,
                "total_chunks": 1,
            },
        )
        for i in range(n)
    ]
    return response


@patch("assistant.search.client")
@patch("assistant.search.embed_query")
def test_hybrid_search_returns_list(mock_embed, mock_client):
    mock_embed.return_value = iter([([0.1] * 384, ([0, 1], [0.5, 0.5]))])
    mock_client.query_points.return_value = _make_query_response(3)

    results = hybrid_search("test query")
    assert isinstance(results, list)
    assert len(results) == 3


@patch("assistant.search.client")
@patch("assistant.search.embed_query")
def test_hybrid_search_result_has_expected_keys(mock_embed, mock_client):
    mock_embed.return_value = iter([([0.1] * 384, ([0, 1], [0.5, 0.5]))])
    mock_client.query_points.return_value = _make_query_response(1)

    results = hybrid_search("test query")
    assert "id" in results[0]
    assert "score" in results[0]
    assert "payload" in results[0]


@patch("assistant.search.client")
@patch("assistant.search.embed_query")
def test_hybrid_search_no_filter(mock_embed, mock_client):
    mock_embed.return_value = iter([([0.1] * 384, ([0, 1], [0.5, 0.5]))])
    mock_client.query_points.return_value = _make_query_response(2)

    hybrid_search("test query", filters=None)
    call_kwargs = mock_client.query_points.call_args.kwargs
    assert call_kwargs["query_filter"] is None


@patch("assistant.search.client")
@patch("assistant.search.embed_query")
def test_hybrid_search_with_sender_filter(mock_embed, mock_client):
    mock_embed.return_value = iter([([0.1] * 384, ([0, 1], [0.5, 0.5]))])
    mock_client.query_points.return_value = _make_query_response(1)

    hybrid_search("invoice", filters={"senders": ["priya@example.com"]})
    call_kwargs = mock_client.query_points.call_args.kwargs
    assert call_kwargs["query_filter"] is not None


@patch("assistant.search.client")
@patch("assistant.search.embed_query")
def test_hybrid_search_empty_results(mock_embed, mock_client):
    mock_embed.return_value = iter([([0.1] * 384, ([0, 1], [0.5, 0.5]))])
    mock_client.query_points.return_value = _make_query_response(0)

    results = hybrid_search("nothing matches")
    assert results == []


# ── build_filter unit tests ───────────────────────────────────────────────────

def test_build_filter_none_returns_none():
    assert build_filter() is None


def test_build_filter_with_senders():
    f = build_filter(senders=["priya@example.com"])
    assert f is not None
    assert f.must[0].key == "sender"


def test_build_filter_with_date_range():
    f = build_filter(
        date_range=["2026-10-01T00:00:00+00:00", "2026-10-17T23:59:59+00:00"],
        intent="range"
    )
    assert f is not None
    assert len(f.must) == 2
