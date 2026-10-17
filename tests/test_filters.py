import pytest
from qdrant_client import models
from assistant.utils.filters import FilterBuilder


def test_build_returns_none_when_empty():
    assert FilterBuilder().build() is None


def test_add_senders_skips_when_empty():
    assert FilterBuilder().add_senders([]).build() is None
    assert FilterBuilder().add_senders(None).build() is None


def test_add_senders_builds_match_any():
    f = FilterBuilder().add_senders(["priya@example.com"]).build()
    assert f is not None
    cond = f.must[0]
    assert cond.key == "sender"
    assert cond.match.any == ["priya@example.com"]


def test_add_senders_multiple():
    f = FilterBuilder().add_senders(["a@x.com", "b@x.com"]).build()
    assert f.must[0].match.any == ["a@x.com", "b@x.com"]


def test_add_participants():
    f = FilterBuilder().add_participants(["priya@example.com"]).build()
    assert f.must[0].key == "participants"


def test_add_labels():
    f = FilterBuilder().add_labels(["INBOX", "CATEGORY_PERSONAL"]).build()
    assert f.must[0].key == "labels"
    assert set(f.must[0].match.any) == {"INBOX", "CATEGORY_PERSONAL"}


def test_add_source():
    f = FilterBuilder().add_source(["gmail"]).build()
    assert f.must[0].key == "source"


def test_add_date_range_range():
    f = FilterBuilder().add_date_range(
        ["2026-10-10T00:00:00+00:00", "2026-10-17T23:59:59+00:00"],
        intent="range"
    ).build()
    assert len(f.must) == 2
    keys = {c.key for c in f.must}
    assert keys == {"date"}


def test_add_date_range_gte():
    f = FilterBuilder().add_date_range(
        ["2026-10-10T00:00:00+00:00"],
        intent="gte"
    ).build()
    assert len(f.must) == 1
    assert f.must[0].range.gte is not None


def test_add_date_range_lte():
    f = FilterBuilder().add_date_range(
        ["2026-10-17T23:59:59+00:00"],
        intent="lte"
    ).build()
    assert len(f.must) == 1
    assert f.must[0].range.lte is not None


def test_add_date_range_sorts_deterministically():
    # Pass dates in wrong order — should still produce gte < lte
    f = FilterBuilder().add_date_range(
        ["2026-10-17T00:00:00+00:00", "2026-10-01T00:00:00+00:00"],
        intent="range"
    ).build()
    gte_cond = next(c for c in f.must if c.range.gte is not None)
    lte_cond = next(c for c in f.must if c.range.lte is not None)
    assert gte_cond.range.gte < lte_cond.range.lte


def test_invalid_date_raises():
    with pytest.raises(ValueError):
        FilterBuilder().add_date_range(["not-a-date"], intent="gte").build()


def test_chaining_multiple_filters():
    f = (
        FilterBuilder()
        .add_senders(["a@x.com"])
        .add_labels(["INBOX"])
        .add_source(["gmail"])
        .build()
    )
    assert len(f.must) == 3
