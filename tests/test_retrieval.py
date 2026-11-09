"""Vector index build, retrieval ranking, and staleness tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rag import KnowledgeBase, KnowledgeBaseError, tokenize
from tests.conftest import FakeEmbedder, create_corpus, make_settings


def _shutdown(kb: KnowledgeBase) -> None:
    try:
        kb.client._system.stop()
    except Exception:  # noqa: BLE001 - already stopped / shared system
        pass
    try:
        from chromadb.api.shared_system_client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
    except Exception:  # noqa: BLE001 - optional cleanup
        pass


@pytest.fixture
def kb(tmp_path: Path):
    settings = make_settings(tmp_path)
    create_corpus(settings.data_dir)
    knowledge_base = KnowledgeBase(settings, FakeEmbedder())
    knowledge_base.build()
    yield knowledge_base
    _shutdown(knowledge_base)


def test_build_writes_manifest_and_cosine_collection(kb: KnowledgeBase) -> None:
    stats = kb.stats()

    assert stats["chunk_count"] >= 8
    assert stats["document_count"] == 4
    assert kb.manifest_path.exists()
    assert kb.collection.metadata["hnsw:space"] == "cosine"
    assert kb.collection.metadata["embedding_model"] == "fake-embedding"


def test_retrieval_ranks_the_matching_document_first(kb: KnowledgeBase) -> None:
    auth_hits = kb.retrieve("Authorization header bearer token 401 expired", top_k=3)
    assert auth_hits[0].source == "api_authentication.md"
    assert auth_hits[0].section == "Bearer tokens"
    assert auth_hits[0].dense_score > 0
    assert auth_hits[0].lexical_score > 0
    assert auth_hits[0].score <= 1.0

    billing_hits = kb.retrieve("duplicate charge invoice refund finance", top_k=3)
    assert billing_hits[0].source == "billing_refunds.md"

    browser_hits = kb.retrieve("clear cookies site data browser cache", top_k=3)
    assert browser_hits[0].source == "browser_troubleshooting.md"

    reset_hits = kb.retrieve("password reset link expired 30 minutes", top_k=3)
    assert reset_hits[0].source == "password_reset.txt"


def test_retrieval_respects_top_k_and_sort_order(kb: KnowledgeBase) -> None:
    hits = kb.retrieve("billing invoice refund", top_k=2)

    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
    assert len({chunk.chunk_id for chunk in hits}) == 2


def test_supporting_chunks_apply_the_similarity_threshold(kb: KnowledgeBase) -> None:
    hits = kb.retrieve("billing invoice refund", top_k=3)
    threshold = kb.settings.min_retrieval_similarity

    supporting = kb.supporting_chunks(hits)
    assert supporting
    assert all(chunk.score >= threshold for chunk in supporting)


def test_staleness_detects_manifest_document_and_model_changes(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    create_corpus(settings.data_dir)
    knowledge_base = KnowledgeBase(settings, FakeEmbedder())
    try:
        knowledge_base.build()
        assert knowledge_base.staleness_reason() is None

        auth = settings.data_dir / "api_authentication.md"
        auth.write_text(auth.read_text(encoding="utf-8") + "\nExtra note.\n", encoding="utf-8")
        assert "modified" in (knowledge_base.staleness_reason() or "").lower()

        (settings.data_dir / "new_doc.md").write_text("# New\n\n## Section\n\nText.\n", encoding="utf-8")
        added_reason = knowledge_base.staleness_reason() or ""
        assert "added" in added_reason.lower()
        assert "new_doc.md" in added_reason

        other_model = KnowledgeBase(settings, FakeEmbedder(model="other-embedding"))
        try:
            model_reason = other_model.staleness_reason() or ""
            assert "other-embedding" in model_reason
        finally:
            _shutdown(other_model)
    finally:
        _shutdown(knowledge_base)


def test_retrieve_without_loaded_collection_raises(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    create_corpus(settings.data_dir)
    knowledge_base = KnowledgeBase(settings, FakeEmbedder())
    try:
        with pytest.raises(KnowledgeBaseError):
            knowledge_base.retrieve("anything")
    finally:
        _shutdown(knowledge_base)


def test_tokenizer_stems_plurals_and_drops_stopwords() -> None:
    assert tokenize("The policies and sessions") == ["policy", "session"]
    assert tokenize("billing invoices") == ["billing", "invoice"]
    assert "the" not in tokenize("the quick brown fox")
