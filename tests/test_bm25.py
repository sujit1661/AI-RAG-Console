"""Tests for BM25 index."""
import pytest
from backend.bm25_index import BM25Index


def test_bm25_basic_search():
    idx = BM25Index()
    idx.add(
        ["Alice is 22 years old", "Bob is 35 years old", "Carol is 22 years old"],
        [{"source": "test.xlsx"}, {"source": "test.xlsx"}, {"source": "test.xlsx"}]
    )
    results = idx.search("age 22", k=5)
    assert len(results) >= 2
    texts = [r[1] for r in results]
    assert any("Alice" in t for t in texts)
    assert any("Carol" in t for t in texts)


def test_bm25_returns_scores():
    idx = BM25Index()
    idx.add(["revenue Q3 2024 was high", "weather is nice today"],
            [{"source": "f"}, {"source": "f"}])
    results = idx.search("revenue Q3")
    assert results[0][0] > results[-1][0]  # first result has higher score


def test_bm25_empty_index():
    idx = BM25Index()
    results = idx.search("anything")
    assert results == []


def test_bm25_delete_by_source():
    idx = BM25Index()
    idx.add(["keep this doc", "delete this doc"],
            [{"source": "keep.pdf"}, {"source": "delete.pdf"}])
    idx.delete_by_source("delete.pdf")
    results = idx.search("delete")
    texts = [r[1] for r in results]
    assert not any("delete this doc" in t for t in texts)


def test_bm25_no_match_returns_empty():
    idx = BM25Index()
    idx.add(["completely unrelated content"], [{"source": "f"}])
    results = idx.search("xyzzy quantum flux")
    assert results == []
