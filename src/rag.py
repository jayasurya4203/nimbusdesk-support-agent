"""Retrieval-Augmented Generation pipeline backed by ChromaDB.

Design notes
------------
* Chunks are embedded with Gemini (document/query task types) and stored in a
  persistent Chroma collection using cosine space.
* Retrieval is hybrid: dense cosine candidates are re-ranked with BM25 so that
  exact tokens such as ``401``, ``SAML``, or ``nk_live_`` are not lost.
* Every chunk keeps source, section, and page metadata for citation and for the
  human handoff report.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .documents import DocumentInfo, load_chunks
from .embeddings import Embedder
from .models import RetrievedChunk

LOGGER = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "do", "does",
    "for", "from", "had", "has", "have", "how", "i", "if", "in", "is", "it", "its", "me",
    "my", "not", "of", "on", "or", "our", "please", "so", "that", "the", "their", "then",
    "there", "this", "to", "was", "we", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "you", "your",
}


class KnowledgeBaseError(RuntimeError):
    """Raised when the vector index is missing or incompatible."""


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [
        _stem(token)
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOPWORDS
    ]


@dataclass
class IndexManifest:
    built_at: str
    embedding_model: str
    embedding_dimensions: int
    chunk_size: int
    chunk_overlap: int
    chunk_count: int
    documents: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_documents(
        cls,
        *,
        embedding_model: str,
        embedding_dimensions: int,
        chunk_size: int,
        chunk_overlap: int,
        chunk_count: int,
        documents: list[DocumentInfo],
    ) -> "IndexManifest":
        return cls(
            built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunk_count=chunk_count,
            documents=[asdict(document) for document in documents],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeBase:
    """Owns ingestion, persistence, and semantic retrieval."""

    def __init__(self, settings: Settings, embedder: Embedder) -> None:
        import chromadb

        self.settings = settings
        self.embedder = embedder
        self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.collection = None
        self._bm25 = None
        self._bm25_ids: list[str] = []
        self._bm25_by_id: dict[str, int] = {}
        self._bm25_tokens: dict[str, set[str]] = {}
        self._space = "cosine"

    # ------------------------------------------------------------------ index
    @property
    def manifest_path(self) -> Path:
        return self.settings.chroma_dir / "index_manifest.json"

    def exists(self) -> bool:
        try:
            self.client.get_collection(self.settings.collection_name)
            return True
        except Exception:  # noqa: BLE001 - Chroma raises varied not-found types
            return False

    def _create_collection(self):
        common = {
            "name": self.settings.collection_name,
            "metadata": {
                "hnsw:space": "cosine",
                "embedding_model": self.embedder.model,
                "embedding_dimensions": int(self.embedder.dimensions),
                "chunk_size": int(self.settings.chunk_size),
                "chunk_overlap": int(self.settings.chunk_overlap),
            },
        }
        try:
            return self.client.create_collection(
                **common,
                configuration={"hnsw": {"space": "cosine"}},
            )
        except (TypeError, ValueError):
            return self.client.create_collection(**common)

    def load(self) -> "KnowledgeBase":
        try:
            self.collection = self.client.get_collection(self.settings.collection_name)
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeBaseError(
                "Knowledge base index not found. Run `python scripts/ingest.py` first."
            ) from exc

        metadata = dict(self.collection.metadata or {})
        self._space = str(metadata.get("hnsw:space", "cosine"))
        self._build_bm25()
        return self

    def build(
        self,
        *,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        """Create a fresh index from ``data/`` and persist a manifest."""
        chunks, documents = load_chunks(
            self.settings.data_dir,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        LOGGER.info("Loaded %d documents into %d chunks", len(documents), len(chunks))

        try:
            self.client.delete_collection(self.settings.collection_name)
        except Exception:  # noqa: BLE001 - nothing to delete on first run
            pass

        collection = self._create_collection()
        batch_size = max(1, min(self.settings.embedding_batch_size, 32))
        total = len(chunks)
        done = 0
        for start in range(0, total, batch_size):
            batch = chunks[start : start + batch_size]
            vectors = self.embedder.embed_documents([chunk.embed_text for chunk in batch])
            collection.add(
                ids=[chunk.chunk_id for chunk in batch],
                embeddings=vectors,
                documents=[chunk.embed_text for chunk in batch],
                metadatas=[chunk.metadata() for chunk in batch],
            )
            done += len(batch)
            if progress:
                progress(done, total, f"Embedded {done}/{total} chunks")

        manifest = IndexManifest.from_documents(
            embedding_model=self.embedder.model,
            embedding_dimensions=self.embedder.dimensions,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            chunk_count=total,
            documents=documents,
        )
        self.manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2), encoding="utf-8"
        )
        self.collection = collection
        self._space = "cosine"
        self._build_bm25()
        return self.stats()

    def staleness_reason(self) -> str | None:
        """Explain why the index no longer matches the data or configuration."""
        if not self.manifest_path.exists():
            return "No index manifest found"
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return "Index manifest is unreadable"

        if manifest.get("embedding_model") != self.embedder.model:
            return (
                f"Index was built with {manifest.get('embedding_model')} but "
                f"{self.embedder.model} is configured"
            )
        if int(manifest.get("embedding_dimensions", -1)) != int(self.embedder.dimensions):
            return "Embedding dimensions changed"
        if int(manifest.get("chunk_size", -1)) != self.settings.chunk_size:
            return "Chunk size changed"
        if int(manifest.get("chunk_overlap", -1)) != self.settings.chunk_overlap:
            return "Chunk overlap changed"

        known = {doc["source"]: doc["sha256"] for doc in manifest.get("documents", [])}
        current = {
            path.name: _sha(path)
            for path in sorted(self.settings.data_dir.iterdir())
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf"}
        }
        if set(known) != set(current):
            missing = set(known) - set(current)
            added = set(current) - set(known)
            return f"Documents changed (added: {sorted(added)}, removed: {sorted(missing)})"
        changed = [name for name, digest in current.items() if known.get(name) != digest]
        if changed:
            return f"Documents modified: {sorted(changed)}"
        return None

    def _build_bm25(self) -> None:
        # BM25+ is used because its IDF floor stays positive on very small
        # corpora, where classic BM25Okapi returns all-zero scores.
        from rank_bm25 import BM25Plus

        if self.collection is None:
            self._bm25 = None
            return
        data = self.collection.get(include=["documents"])
        ids = list(data.get("ids") or [])
        documents = list(data.get("documents") or [])
        if not ids:
            self._bm25 = None
            self._bm25_ids = []
            self._bm25_by_id = {}
            self._bm25_tokens = {}
            return
        corpus = [tokenize(document or "") for document in documents]
        try:
            self._bm25 = BM25Plus(corpus)
        except Exception:  # noqa: BLE001 - tiny corpora can fail inside BM25
            LOGGER.warning("BM25 index could not be built; using dense retrieval only")
            self._bm25 = None
        self._bm25_ids = ids
        self._bm25_by_id = {chunk_id: index for index, chunk_id in enumerate(ids)}
        self._bm25_tokens = {
            chunk_id: set(tokens) for chunk_id, tokens in zip(ids, corpus)
        }

    # --------------------------------------------------------------- retrieval
    def _similarity(self, distance: float) -> float:
        if self._space == "l2":
            # For unit-normalized vectors: ||a-b||^2 = 2 - 2*cos(a,b)
            return max(0.0, 1.0 - (distance**2) / 2.0)
        return max(0.0, 1.0 - distance)

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        if self.collection is None:
            raise KnowledgeBaseError("Knowledge base is not loaded")
        total = self.collection.count()
        if total == 0:
            return []

        limit = top_k or self.settings.top_k
        candidates = max(limit, self.settings.candidate_k)
        n_results = min(candidates, total)
        query_vector = self.embedder.embed_query(query)
        result = self.collection.query(
            query_embeddings=[query_vector],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        lexical_scores: dict[str, float] = {}
        query_tokens = tokenize(query)
        query_token_set = set(query_tokens)
        if self._bm25 is not None and ids:
            scores = self._bm25.get_scores(query_tokens)
            for chunk_id in ids:
                index = self._bm25_by_id.get(chunk_id)
                if index is None:
                    continue
                # BM25+ adds a delta for absent terms; require real overlap.
                if query_token_set.isdisjoint(self._bm25_tokens.get(chunk_id, set())):
                    lexical_scores[chunk_id] = 0.0
                else:
                    lexical_scores[chunk_id] = float(scores[index])
        max_lexical = max(lexical_scores.values(), default=0.0)

        chunks: list[RetrievedChunk] = []
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            metadata = metadata or {}
            dense = self._similarity(float(distance))
            lexical = lexical_scores.get(chunk_id, 0.0) / max_lexical if max_lexical > 0 else 0.0
            score = dense
            if self.settings.enable_lexical_rerank:
                weight = self.settings.lexical_weight
                score = (1.0 - weight) * dense + weight * lexical
            chunks.append(
                RetrievedChunk(
                    chunk_id=str(chunk_id),
                    text=str(document or ""),
                    source=str(metadata.get("source", "unknown")),
                    title=str(metadata.get("title", "")),
                    section=str(metadata.get("section", "")),
                    page=int(metadata["page"]) if metadata.get("page") else None,
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    score=max(0.0, min(1.0, score)),
                    dense_score=max(0.0, min(1.0, dense)),
                    lexical_score=max(0.0, min(1.0, lexical)),
                )
            )

        chunks.sort(key=lambda chunk: chunk.score, reverse=True)
        return chunks[:limit]

    def supporting_chunks(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        threshold = self.settings.min_retrieval_similarity
        return [chunk for chunk in chunks if chunk.score >= threshold]

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        manifest: dict[str, Any] = {}
        if self.manifest_path.exists():
            try:
                manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                manifest = {}
        count = self.collection.count() if self.collection is not None else 0
        return {
            "collection": self.settings.collection_name,
            "chunk_count": count,
            "document_count": len(manifest.get("documents", [])),
            "built_at": manifest.get("built_at"),
            "embedding_model": manifest.get("embedding_model", self.embedder.model),
            "embedding_dimensions": manifest.get(
                "embedding_dimensions", self.embedder.dimensions
            ),
            "chunk_size": manifest.get("chunk_size", self.settings.chunk_size),
            "chunk_overlap": manifest.get("chunk_overlap", self.settings.chunk_overlap),
            "documents": manifest.get("documents", []),
            "top_k": self.settings.top_k,
            "min_retrieval_similarity": self.settings.min_retrieval_similarity,
        }


def _sha(path: Path) -> str:
    from .documents import file_sha256

    return file_sha256(path)
