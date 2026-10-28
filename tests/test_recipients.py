import pytest
from unittest.mock import patch, MagicMock
from assistant.recipients import resolve_sender


def _make_point(sender, participants):
    point = MagicMock()
    point.payload = {"sender": sender, "participants": participants}
    return point


@patch("assistant.recipients.get_client")
def test_resolve_sender_returns_list(mock_get_client):
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = (
        [_make_point("Priya Raman <priya@example.com>", ["priya@example.com", "john@example.com"])],
        None,
    )
    result = resolve_sender("Priya")
    assert isinstance(result, list)


@patch("assistant.recipients.get_client")
def test_resolve_sender_deduplicates(mock_get_client):
    mock_client = mock_get_client.return_value
    # Same sender across two points — should appear once
    mock_client.scroll.return_value = (
        [
            _make_point("priya@example.com", ["priya@example.com"]),
            _make_point("priya@example.com", ["priya@example.com"]),
        ],
        None,
    )
    result = resolve_sender("Priya")
    assert result.count("priya@example.com") == 1


@patch("assistant.recipients.get_client")
def test_resolve_sender_includes_participants(mock_get_client):
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = (
        [_make_point("sender@example.com", ["priya@example.com", "john@example.com"])],
        None,
    )
    result = resolve_sender("Priya")
    assert "priya@example.com" in result
    assert "john@example.com" in result


@patch("assistant.recipients.get_client")
def test_resolve_sender_empty_results(mock_get_client):
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = ([], None)
    result = resolve_sender("nobody")
    assert result == []


@patch("assistant.recipients.get_client")
def test_resolve_sender_no_duplicate_between_sender_and_participants(mock_get_client):
    mock_client = mock_get_client.return_value
    # sender also appears in participants — should appear only once
    mock_client.scroll.return_value = (
        [_make_point("priya@example.com", ["priya@example.com", "john@example.com"])],
        None,
    )
    result = resolve_sender("Priya")
    assert result.count("priya@example.com") == 1
