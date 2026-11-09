#!/usr/bin/env python3
"""Build (or inspect) the knowledge-base vector index.

    python scripts/ingest.py --dry-run   # parse + chunk, no API calls
    python scripts/ingest.py --check     # report index freshness, no API calls
    python scripts/ingest.py             # embed documents and rebuild the index
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import Settings  # noqa: E402
from src.documents import load_chunks  # noqa: E402


class _MetadataOnlyEmbedder:
    """Used by --check so freshness can be verified without an API key."""

    def __init__(self, model: str, dimensions: int) -> None:
        self.model = model
        self.dimensions = dimensions

    def embed_documents(self, texts):  # pragma: no cover - never called
        raise NotImplementedError

    def embed_query(self, text):  # pragma: no cover - never called
        raise NotImplementedError


def _progress(done: int, total: int, label: str) -> None:
    percent = (done / total * 100) if total else 100.0
    print(f"\r  {label:<38} {percent:5.1f}%", end="", flush=True)


def _print_table(documents) -> None:
    print(f"\n{'Document':38s} {'Type':8s} {'Pages':>5s} {'Segments':>9s} {'Chunks':>7s}")
    print("-" * 72)
    for doc in documents:
        print(
            f"{doc.source:38s} {doc.doc_type:8s} {doc.pages:5d} "
            f"{doc.segments:9d} {doc.chunks:7d}"
        )
    print("-" * 72)
    print(
        f"{'TOTAL ' + str(len(documents)) + ' documents':38s} {'':8s} {'':5s} "
        f"{sum(d.segments for d in documents):9d} {sum(d.chunks for d in documents):7d}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest NimbusDesk support documents")
    parser.add_argument("--dry-run", action="store_true", help="Parse and chunk without embedding")
    parser.add_argument("--check", action="store_true", help="Report index freshness and exit")
    args = parser.parse_args()

    settings = Settings.load()

    if args.dry_run:
        chunks, documents = load_chunks(
            settings.data_dir,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        _print_table(documents)
        print(
            f"\nChunking: {settings.chunk_size} chars / {settings.chunk_overlap} overlap "
            f"-> {len(chunks)} chunks"
        )
        pdf_chunks = [chunk for chunk in chunks if chunk.page is not None]
        print(f"Chunks with page metadata: {len(pdf_chunks)}")
        return 0

    from src.rag import KnowledgeBase

    if args.check:
        embedder = _MetadataOnlyEmbedder(
            settings.embedding_model, settings.embedding_dimensions
        )
        kb = KnowledgeBase(settings, embedder)
        if not kb.exists():
            print("Index missing. Run `python scripts/ingest.py`.")
            return 1
        kb.load()
        reason = kb.staleness_reason()
        print(f"Collection: {settings.collection_name}")
        print(f"Chunks: {kb.collection.count()}")
        print(f"Staleness: {reason or 'up to date'}")
        return 0 if reason is None else 1

    settings.require_api_key()
    from src.embeddings import GeminiEmbedder

    embedder = GeminiEmbedder(
        api_key=settings.gemini_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        max_retries=settings.max_retries,
        base_delay_s=settings.retry_base_delay_s,
        inputs_per_minute=settings.embedding_inputs_per_minute,
    )
    print(f"Embedding with {settings.embedding_model} ({settings.embedding_dimensions} dims)")
    kb = KnowledgeBase(settings, embedder)
    stats = kb.build(progress=_progress)
    print()
    _print_table([SimpleNamespace(**doc) for doc in stats["documents"]])
    print(
        f"\nIndexed {stats['chunk_count']} chunks in {settings.chroma_dir} "
        f"at {stats['built_at']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
