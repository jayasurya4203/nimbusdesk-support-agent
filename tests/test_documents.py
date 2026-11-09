"""Ingestion, parsing, chunking, and metadata tests."""

from __future__ import annotations

from src.config import PROJECT_ROOT
from src.documents import (
    chunk_segments,
    file_sha256,
    load_chunks,
    load_segments,
)

DATA_DIR = PROJECT_ROOT / "data"


def test_real_corpus_meets_assignment_requirements() -> None:
    chunks, documents = load_chunks(DATA_DIR, chunk_size=900, chunk_overlap=150)

    assert 10 <= len(documents) <= 20
    assert len(chunks) >= 100
    assert any(document.doc_type == "pdf" for document in documents)
    assert {chunk.chunk_id for chunk in chunks}.__len__() == len(chunks)
    assert all(chunk.source and chunk.text.strip() for chunk in chunks)

    documented = {document.source for document in documents}
    assert {chunk.source for chunk in chunks} == documented
    assert all(document.chunks >= 1 for document in documents)


def test_pdf_chunks_carry_page_metadata_and_clean_text() -> None:
    chunks, _ = load_chunks(DATA_DIR, chunk_size=900, chunk_overlap=150)
    pdf_chunks = [chunk for chunk in chunks if chunk.doc_type == "pdf"]

    assert pdf_chunks, "expected at least one PDF in the knowledge base"
    assert {chunk.source for chunk in pdf_chunks} == {"password_reset_guide.pdf"}
    assert {chunk.page for chunk in pdf_chunks} == {1, 2, 3}
    for chunk in pdf_chunks:
        assert chunk.page is not None
        assert "NimbusDesk Support | KB-" not in chunk.text
        assert "Page " + str(chunk.page) not in chunk.text


def test_markdown_segments_use_document_title_and_headings() -> None:
    segments = load_segments(DATA_DIR)
    auth = [segment for segment in segments if segment.source == "api_authentication.md"]

    assert auth
    assert auth[0].title == "NimbusDesk API Authentication"
    assert any(segment.section == "Required headers" for segment in auth)
    assert all(segment.page is None for segment in auth)


def test_chunk_metadata_and_embed_text_preserve_source_and_page() -> None:
    segments = load_segments(DATA_DIR)
    chunks = chunk_segments(segments, chunk_size=900, chunk_overlap=150)
    pdf_chunk = next(chunk for chunk in chunks if chunk.page == 2)

    metadata = pdf_chunk.metadata()
    assert metadata["source"] == "password_reset_guide.pdf"
    assert metadata["page"] == 2
    assert metadata["doc_type"] == "pdf"
    assert pdf_chunk.embed_text.startswith(f"{pdf_chunk.title} > {pdf_chunk.section}\n")
    assert pdf_chunk.text in pdf_chunk.embed_text


def test_chunking_splits_long_sections_and_keeps_ids_unique() -> None:
    from src.documents import ParsedSegment

    long_body = " ".join(f"Step {index}: verify the connector setting." for index in range(120))
    source = "long_guide.md"
    segments = [
        ParsedSegment(
            text=f"## Troubleshooting\n\n{long_body}",
            source=source,
            title="Long Guide",
            section="Troubleshooting",
            page=None,
            doc_type="markdown",
        )
    ]
    chunks = chunk_segments(segments, chunk_size=200, chunk_overlap=40)

    assert len(chunks) > 1
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all(chunk.source == source for chunk in chunks)
    assert all(chunk.section == "Troubleshooting" for chunk in chunks)
    assert chunks[0].chunk_id == "long_guide.md#000"


def test_chunking_rejects_invalid_overlap() -> None:
    import pytest

    from src.documents import ParsedSegment

    segment = ParsedSegment(
        text="hello",
        source="a.md",
        title="A",
        section="General",
        page=None,
        doc_type="markdown",
    )
    with pytest.raises(ValueError):
        chunk_segments([segment], chunk_size=100, chunk_overlap=100)


def test_file_hash_is_stable() -> None:
    path = DATA_DIR / "refund_and_dispute_policy.md"
    assert file_sha256(path) == file_sha256(path)
    assert len(file_sha256(path)) == 64
