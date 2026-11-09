"""Knowledge base loading, parsing, and chunking.

Each chunk carries source-document, section, and (for PDFs) page metadata so
that citations and the human handoff can point a human agent at the exact
passage that grounded the answer.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}

_TXT_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Z0-9 ,&/()'_-]{2,}$")
_UNDERLINE_RE = re.compile(r"^[=\-_]{5,}\s*$")
_MD_H1_RE = re.compile(r"^#\s+(.+)$")
_MD_H2_RE = re.compile(r"^##\s+(.+)$")
_FENCE_RE = re.compile(r"^\s*```")
_PDF_FOOTER_RE = re.compile(r"^NimbusDesk Support \| KB-\d+ \|.*$")
_PDF_PAGE_RE = re.compile(r"^Page \d+$")
_PDF_SECTION_RE = re.compile(r"^\d+\.\s+[A-Z].{2,70}$")


@dataclass
class ParsedSegment:
    """A titled, page-scoped portion of a document before chunking."""

    text: str
    source: str
    title: str
    section: str
    page: int | None
    doc_type: str


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source: str
    title: str
    section: str
    page: int | None
    doc_type: str
    chunk_index: int
    embed_text: str = ""

    def metadata(self) -> dict[str, object]:
        meta: dict[str, object] = {
            "source": self.source,
            "title": self.title,
            "section": self.section,
            "doc_type": self.doc_type,
            "chunk_index": self.chunk_index,
            "chars": len(self.text),
        }
        if self.page is not None:
            meta["page"] = self.page
        return meta


@dataclass
class DocumentInfo:
    source: str
    title: str
    doc_type: str
    sha256: str
    pages: int
    chunks: int
    segments: int = 0


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _title_from_filename(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


def _flush(
    segments: list[ParsedSegment],
    buffer: list[str],
    *,
    source: str,
    title: str,
    section: str,
    page: int | None,
    doc_type: str,
) -> None:
    text = "\n".join(buffer).strip()
    if text:
        segments.append(
            ParsedSegment(
                text=text,
                source=source,
                title=title,
                section=section or "General",
                page=page,
                doc_type=doc_type,
            )
        )
    buffer.clear()


def _parse_markdown(path: Path) -> list[ParsedSegment]:
    lines = path.read_text(encoding="utf-8").splitlines()
    title = _title_from_filename(path)
    section = "Overview"
    segments: list[ParsedSegment] = []
    buffer: list[str] = []
    in_fence = False

    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buffer.append(line)
            continue
        if not in_fence:
            h1 = _MD_H1_RE.match(line)
            h2 = _MD_H2_RE.match(line)
            if h1 and not segments and not "".join(buffer).strip():
                title = h1.group(1).strip()
                continue
            if h2:
                _flush(
                    segments,
                    buffer,
                    source=path.name,
                    title=title,
                    section=section,
                    page=None,
                    doc_type="markdown",
                )
                section = h2.group(1).strip()
                continue
        buffer.append(line)

    _flush(
        segments,
        buffer,
        source=path.name,
        title=title,
        section=section,
        page=None,
        doc_type="markdown",
    )
    return segments


def _parse_text(path: Path) -> list[ParsedSegment]:
    lines = path.read_text(encoding="utf-8").splitlines()
    non_empty = [line.strip() for line in lines if line.strip()]
    title = non_empty[0] if non_empty else _title_from_filename(path)
    section = "General"
    segments: list[ParsedSegment] = []
    buffer: list[str] = []

    for line in lines:
        stripped = line.strip()
        if _UNDERLINE_RE.match(stripped):
            continue
        if _TXT_HEADING_RE.match(stripped):
            _flush(
                segments,
                buffer,
                source=path.name,
                title=title,
                section=section,
                page=None,
                doc_type="text",
            )
            section = stripped
            continue
        buffer.append(line)

    _flush(
        segments,
        buffer,
        source=path.name,
        title=title,
        section=section,
        page=None,
        doc_type="text",
    )
    return segments


def _clean_pdf_text(text: str) -> str:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if _PDF_FOOTER_RE.match(stripped) or _PDF_PAGE_RE.match(stripped):
            continue
        kept.append(line.rstrip())
    cleaned = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _pdf_section(text: str, page_number: int) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if _PDF_SECTION_RE.match(stripped):
            return stripped
    return f"Page {page_number}"


def _parse_pdf(path: Path) -> tuple[list[ParsedSegment], int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    title = _title_from_filename(path)
    if reader.metadata and reader.metadata.title:
        title = str(reader.metadata.title).strip() or title

    segments: list[ParsedSegment] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = _clean_pdf_text(page.extract_text() or "")
        if not text:
            continue
        segments.append(
            ParsedSegment(
                text=text,
                source=path.name,
                title=title,
                section=_pdf_section(text, page_number),
                page=page_number,
                doc_type="pdf",
            )
        )
    return segments, len(reader.pages)


def load_segments(data_dir: Path) -> list[ParsedSegment]:
    """Parse every supported file in ``data_dir`` into titled segments."""
    if not data_dir.exists():
        raise FileNotFoundError(f"Knowledge base directory not found: {data_dir}")

    segments: list[ParsedSegment] = []
    for path in sorted(data_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        suffix = path.suffix.lower()
        if suffix == ".md":
            segments.extend(_parse_markdown(path))
        elif suffix == ".txt":
            segments.extend(_parse_text(path))
        else:
            pdf_segments, _ = _parse_pdf(path)
            segments.extend(pdf_segments)
    if not segments:
        raise ValueError(f"No supported documents found in {data_dir}")
    return segments


def _splitter(chunk_size: int, chunk_overlap: int):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
        keep_separator=True,
    )


def chunk_segments(
    segments: Sequence[ParsedSegment],
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
) -> list[Chunk]:
    """Split segments into overlapping chunks while preserving metadata."""
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    splitter = _splitter(chunk_size, chunk_overlap)
    counters: dict[str, int] = {}
    chunks: list[Chunk] = []

    for segment in segments:
        for body in splitter.split_text(segment.text):
            body = body.strip()
            if not body:
                continue
            index = counters.get(segment.source, 0)
            counters[segment.source] = index + 1
            embed_text = f"{segment.title} > {segment.section}\n{body}"
            chunks.append(
                Chunk(
                    chunk_id=f"{segment.source}#{index:03d}",
                    text=body,
                    source=segment.source,
                    title=segment.title,
                    section=segment.section,
                    page=segment.page,
                    doc_type=segment.doc_type,
                    chunk_index=index,
                    embed_text=embed_text,
                )
            )
    return chunks


def load_chunks(
    data_dir: Path,
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
) -> tuple[list[Chunk], list[DocumentInfo]]:
    """Load all documents and return chunks plus per-document statistics."""
    segments = load_segments(data_dir)
    chunks = chunk_segments(segments, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    by_source: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_source.setdefault(chunk.source, []).append(chunk)

    documents: list[DocumentInfo] = []
    for path in sorted(data_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        doc_chunks = by_source.get(path.name, [])
        doc_segments = [segment for segment in segments if segment.source == path.name]
        pages = max((segment.page or 0 for segment in doc_segments), default=0)
        documents.append(
            DocumentInfo(
                source=path.name,
                title=doc_chunks[0].title if doc_chunks else _title_from_filename(path),
                doc_type=path.suffix.lstrip(".").lower(),
                sha256=file_sha256(path),
                pages=pages,
                chunks=len(doc_chunks),
                segments=len(doc_segments),
            )
        )
    return chunks, documents


def iter_batches(items: Iterable[Chunk], size: int):
    batch: list[Chunk] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
