import pytest
from unittest.mock import patch
from datetime import datetime
from assistant.tools.gmail import gmail_search, _date_filter
from assistant.tools.errors import ToolError


def _result(external_id, chunk_index, total_chunks=1, title="Subject", score=0.5):
    return {
        "id": f"{external_id}-{chunk_index}",
        "score": score,
        "payload": {
            "source": "gmail",
            "external_id": external_id,
            "thread_id": f"thread-{external_id}",
            "title": title,
            "sender": "Amazon Web Services <invoicing@aws.com>",
            "participants": ["invoicing@aws.com", "me@example.com"],
            "date": "2026-10-01T22:12:13+00:00",
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "chunk_text": f"{external_id} part {chunk_index}",
            "content_hash": "abc",
        },
    }


# ── grouping and result shape ─────────────────────────────────────────────────

@patch("assistant.tools.gmail.hybrid_search")
def test_chunks_of_one_email_are_merged_even_when_not_adjacent(mock_search):
    # Score order puts another email between the two AWS chunks — groupby lost the first one
    mock_search.return_value = [_result("aws", 1, 2), _result("budget", 0), _result("aws", 0, 2)]
    emails = gmail_search("invoice")
    assert [e["external_id"] for e in emails] == ["aws", "budget"]
    assert emails[0]["text"] == "aws part 0\n\naws part 1"  # chunk_index order, not score order
    assert emails[0]["parts"] == "2 of 2"


@patch("assistant.tools.gmail.hybrid_search")
def test_same_title_different_emails_stay_separate(mock_search):
    mock_search.return_value = [_result("sept", 0, title="AWS Invoice"), _result("aug", 0, title="AWS Invoice")]
    assert len(gmail_search("invoice")) == 2


@patch("assistant.tools.gmail.hybrid_search")
def test_partial_email_reports_parts(mock_search):
    mock_search.return_value = [_result("long", 3, total_chunks=8)]
    assert gmail_search("invoice")[0]["parts"] == "1 of 8"


@patch("assistant.tools.gmail.hybrid_search")
def test_result_has_only_useful_fields(mock_search):
    mock_search.return_value = [_result("aws", 0)]
    assert set(gmail_search("invoice")[0]) == {
        "external_id", "thread_id", "title", "sender", "date", "participants", "parts", "text",
    }


@patch("assistant.tools.gmail.hybrid_search")
def test_no_results_is_empty_list_not_error(mock_search):
    mock_search.return_value = []
    assert gmail_search("nothing") == []


def test_empty_query_raises_tool_error():
    with pytest.raises(ToolError, match="query is empty"):
        gmail_search("")


# ── date filters ──────────────────────────────────────────────────────────────

@pytest.fixture
def utc_user():
    # Pin the timezone so these tests don't depend on the computer running them
    with patch("assistant.tools.gmail.USER_TIMEZONE", "UTC"):
        yield


@pytest.mark.parametrize("date_from, date_to, expected", [
    ("2026-10-01", "2026-10-07", (["2026-10-01T00:00:00+00:00", "2026-10-08T00:00:00+00:00"], "half_open")),
    ("2026-10-01", None, (["2026-10-01T00:00:00+00:00"], "gte")),
    (None, "2026-10-07", (["2026-10-08T00:00:00+00:00"], "lt")),
])
@patch("assistant.tools.gmail.hybrid_search", return_value=[])
def test_dates_become_date_range_and_intent(mock_search, utc_user, date_from, date_to, expected):
    gmail_search("invoice", date_from=date_from, date_to=date_to)
    filters = mock_search.call_args.args[1]
    assert (filters["date_range"], filters["intent"]) == expected


@patch("assistant.tools.gmail.USER_TIMEZONE", "Asia/Kolkata")
def test_dates_use_the_users_timezone():
    # A Kolkata day starts 5h30m before a UTC day
    assert _date_filter("2026-10-01", "2026-10-07")[0] == [
        "2026-10-01T00:00:00+05:30", "2026-10-08T00:00:00+05:30",
    ]


@patch("assistant.tools.gmail.USER_TIMEZONE", "Europe/Dublin")
def test_offset_follows_daylight_saving_for_each_date():
    # Dublin moves from +01:00 (summer) to +00:00 on 2026-10-25, so that day starts on +01:00 and the next midnight is +00:00
    assert _date_filter("2026-10-25", "2026-10-25")[0] == [
        "2026-10-25T00:00:00+01:00", "2026-10-26T00:00:00+00:00",
    ]
    assert _date_filter("2026-11-01", None)[0] == ["2026-11-01T00:00:00+00:00"]


@patch("assistant.tools.gmail.USER_TIMEZONE", "")
def test_no_setting_falls_back_to_the_computers_timezone():
    expected = datetime(2026, 10, 1).astimezone().isoformat()
    assert _date_filter("2026-10-01", None)[0] == [expected]


@patch("assistant.tools.gmail.hybrid_search", return_value=[])
def test_no_dates_no_date_filter(mock_search):
    gmail_search("invoice")
    assert "date_range" not in mock_search.call_args.args[1]


@pytest.mark.parametrize("kwargs", [{"date_from": "last week"}, {"date_to": "2026-13-01"}])
def test_bad_date_raises_tool_error(kwargs):
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        gmail_search("invoice", **kwargs)


def test_date_from_after_date_to_raises_tool_error():
    with pytest.raises(ToolError, match="after"):
        gmail_search("invoice", date_from="2026-10-07", date_to="2026-10-01")


# ── sender ────────────────────────────────────────────────────────────────────

@patch("assistant.tools.gmail.hybrid_search", return_value=[])
@patch("assistant.tools.gmail.resolve_sender", return_value=["Amazon Web Services <invoicing@aws.com>"])
def test_sender_is_resolved_into_senders_filter(mock_resolve, mock_search):
    gmail_search("invoice", sender="AWS")
    mock_resolve.assert_called_once_with("AWS")
    assert mock_search.call_args.args[1]["senders"] == ["Amazon Web Services <invoicing@aws.com>"]


@patch("assistant.tools.gmail.hybrid_search")
@patch("assistant.tools.gmail.resolve_sender", return_value=[])
def test_unknown_sender_raises_instead_of_searching_unfiltered(mock_resolve, mock_search):
    with pytest.raises(ToolError, match="No sender matching 'Zzyzx'"):
        gmail_search("invoice", sender="Zzyzx")
    mock_search.assert_not_called()


@patch("assistant.tools.gmail.hybrid_search", return_value=[])
@patch("assistant.tools.gmail.resolve_sender")
def test_no_sender_no_lookup(mock_resolve, mock_search):
    gmail_search("invoice")
    mock_resolve.assert_not_called()
    assert "senders" not in mock_search.call_args.args[1]
