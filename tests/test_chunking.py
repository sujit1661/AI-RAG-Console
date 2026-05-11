"""Tests for chunking logic."""
import pytest
from backend.chunking import chunk_text, chunk_text_with_pages, chunk_excel_text


def test_chunk_text_basic():
    text = "word " * 300  # 1500 chars
    chunks = chunk_text(text)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)
    assert all(len(c) > 0 for c in chunks)


def test_chunk_text_short():
    text = "Short text."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == "Short text."


def test_chunk_text_with_pages():
    text = "Page one content. " * 50 + "Page two content. " * 50
    page_info = [(0, len(text) // 2, 1), (len(text) // 2, len(text), 2)]
    chunks = chunk_text_with_pages(text, page_info)
    assert len(chunks) >= 1
    assert all(isinstance(c, tuple) and len(c) == 2 for c in chunks)
    assert all(isinstance(c[0], str) for c in chunks)
    assert all(c[1] in (1, 2, None) for c in chunks)


def test_chunk_excel_text_basic():
    excel_text = """## Sheet: Sheet1
Rows: 3, Columns: 2
Columns: Name, Age

### Data Rows
Name: Alice | Age: 25
Name: Bob | Age: 30
Name: Carol | Age: 22"""
    chunks = chunk_excel_text(excel_text)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)
    # Each chunk should contain column info
    assert any("Name" in c for c in chunks)


def test_chunk_excel_rows_per_chunk():
    # 60 rows should produce at least 3 chunks with rows_per_chunk=20
    rows = "\n".join([f"Name: Person{i} | Age: {20+i}" for i in range(60)])
    excel_text = f"## Sheet: Data\nRows: 60, Columns: 2\nColumns: Name, Age\n\n### Data Rows\n{rows}"
    chunks = chunk_excel_text(excel_text, rows_per_chunk=20)
    assert len(chunks) >= 3
