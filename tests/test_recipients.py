import pytest
from unittest.mock import patch, MagicMock
from assistant.recipients import resolve_sender


def _make_point(sender, participants=None):
    point = MagicMock()
    point.payload = {"sender": sender, "participants": participants or []}
    return point


@patch("assistant.recipients.get_client")
def test_resolve_sender_returns_list(mock_get_client):
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = ([_make_point("Priya Raman <priya@example.com>")], None)
    result = resolve_sender("Priya")
    assert isinstance(result, list)


@patch("assistant.recipients.get_client")
def test_resolve_sender_returns_stored_sender_strings(mock_get_client):
    # The sender filter is an exact match, so the result must be the stored "Name <addr>" string
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = ([_make_point("Priya Raman <priya@example.com>")], None)
    assert resolve_sender("Priya") == ["Priya Raman <priya@example.com>"]


@patch("assistant.recipients.get_client")
def test_resolve_sender_deduplicates(mock_get_client):
    # Every chunk of every email from Priya carries the same sender — it should appear once
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = (
        [_make_point("Priya Raman <priya@example.com>"), _make_point("Priya Raman <priya@example.com>")],
        None,
    )
    assert resolve_sender("Priya") == ["Priya Raman <priya@example.com>"]


@patch("assistant.recipients.get_client")
def test_resolve_sender_ignores_participants(mock_get_client):
    # Participants include the user's own address on every email; adding them would make the filter match everything
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = (
        [_make_point("Priya Raman <priya@example.com>", ["priya@example.com", "me@example.com"])],
        None,
    )
    result = resolve_sender("Priya")
    assert "me@example.com" not in result
    assert "priya@example.com" not in result


@patch("assistant.recipients.get_client")
def test_resolve_sender_filters_on_sender_field_only(mock_get_client):
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = ([], None)
    resolve_sender("Priya")
    conditions = mock_client.scroll.call_args.kwargs["scroll_filter"].must
    assert [c.key for c in conditions] == ["sender"]


@patch("assistant.recipients.get_client")
def test_resolve_sender_reads_every_page(mock_get_client):
    # scroll returns one page at a time; senders on later pages must not be missed
    mock_client = mock_get_client.return_value
    mock_client.scroll.side_effect = [
        ([_make_point("Priya Raman <priya@example.com>")], "next-page"),
        ([_make_point("Priya R <priya@work.example.com>")], None),
    ]
    result = resolve_sender("Priya")
    assert result == ["Priya R <priya@work.example.com>", "Priya Raman <priya@example.com>"]
    assert mock_client.scroll.call_count == 2
    assert mock_client.scroll.call_args.kwargs["offset"] == "next-page"


@patch("assistant.recipients.get_client")
def test_resolve_sender_empty_results(mock_get_client):
    mock_client = mock_get_client.return_value
    mock_client.scroll.return_value = ([], None)
    assert resolve_sender("nobody") == []
