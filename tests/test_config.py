"""Configuration loading, validation, and feedback logging tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import PROJECT_ROOT, ConfigurationError, Settings
from src.feedback import record_feedback

_ENV_KEYS = (
    "GEMINI_API_KEY",
    "CHAT_MODEL",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    "TOP_K",
    "CANDIDATE_K",
    "MIN_RETRIEVAL_SIMILARITY",
    "SENSITIVE_ESCALATION_MODE",
    "EXTRA_SENSITIVE_TERMS",
    "DATA_DIR",
    "CHROMA_DIR",
    "ENABLE_LEXICAL_RERANK",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
)


@pytest.fixture
def clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_configuration(clean_env, tmp_path: Path) -> None:
    settings = Settings.load(env_file=tmp_path / "missing.env")

    assert settings.chat_model == "gemini-2.5-flash"
    assert settings.embedding_model == "gemini-embedding-001"
    assert settings.embedding_dimensions == 768
    assert settings.top_k == 4
    assert settings.candidate_k == 15
    assert settings.min_retrieval_similarity == pytest.approx(0.52)
    assert settings.chunk_size == 900
    assert settings.chunk_overlap == 150
    assert settings.max_turns_before_escalation == 6
    assert settings.frustration_streak_threshold == 2
    assert settings.sensitive_mode == "actions_only"
    assert settings.require_citations is True
    assert settings.has_api_key is False


def test_environment_overrides_are_parsed(clean_env, monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GEMINI_API_KEY=abc123",
                "CHAT_MODEL=gemini-test",
                "TOP_K=6",
                "CANDIDATE_K=20",
                "MIN_RETRIEVAL_SIMILARITY=0.61",
                "SENSITIVE_ESCALATION_MODE=always",
                "EXTRA_SENSITIVE_TERMS=Enterprise Contract, SOC 2",
                "DATA_DIR=custom_data",
                f"CHROMA_DIR={tmp_path / 'chroma_custom'}",
                "ENABLE_LEXICAL_RERANK=false",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.load(env_file=env_file)

    assert settings.gemini_api_key == "abc123"
    assert settings.has_api_key is True
    assert settings.chat_model == "gemini-test"
    assert settings.top_k == 6
    assert settings.candidate_k == 20
    assert settings.min_retrieval_similarity == pytest.approx(0.61)
    assert settings.sensitive_mode == "always"
    assert settings.extra_sensitive_terms == ("enterprise contract", "soc 2")
    assert settings.data_dir == PROJECT_ROOT / "custom_data"
    assert settings.chroma_dir == tmp_path / "chroma_custom"
    assert settings.enable_lexical_rerank is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("TOP_K", "four"),
        ("MIN_RETRIEVAL_SIMILARITY", "high"),
        ("ENABLE_LEXICAL_RERANK", "maybe"),
    ],
)
def test_invalid_environment_values_raise(
    clean_env, monkeypatch, tmp_path: Path, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)

    with pytest.raises(ConfigurationError):
        Settings.load(env_file=tmp_path / "missing.env")


def test_require_api_key_raises_when_missing() -> None:
    settings = Settings(gemini_api_key="")

    assert settings.has_api_key is False
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        settings.require_api_key()


def test_with_overrides_validates_the_result() -> None:
    settings = Settings()

    overridden = settings.with_overrides(top_k=2, min_retrieval_similarity=0.4)
    assert overridden.top_k == 2
    assert settings.top_k == 4  # original is unchanged

    with pytest.raises(ConfigurationError):
        settings.with_overrides(top_k=0)
    with pytest.raises(ConfigurationError):
        settings.with_overrides(sensitive_mode="sometimes")
    with pytest.raises(ConfigurationError):
        settings.with_overrides(min_retrieval_similarity=1.5)
    with pytest.raises(ConfigurationError):
        settings.with_overrides(chunk_overlap=900)


def test_feedback_is_appended_as_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "feedback" / "feedback.jsonl"

    first = record_feedback(
        path,
        session_id="S-1",
        persona="Frustrated User",
        rating="down",
        message="Nothing works!",
        response_excerpt="I'm sorry...",
        sources=["browser_troubleshooting.txt"],
        comment="Too generic.",
        escalated=False,
    )
    record_feedback(
        path,
        session_id="S-2",
        persona="Technical Expert",
        rating="up",
        message="Bearer token 401",
        response_excerpt="Check the header.",
        sources=["api_authentication.md"],
        escalated=True,
    )

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    entries = [json.loads(line) for line in lines]
    assert entries[0]["rating"] == "down"
    assert entries[0]["comment"] == "Too generic."
    assert entries[1]["escalated"] is True
    assert first["session_id"] == "S-1"

    with pytest.raises(ValueError):
        record_feedback(
            path,
            session_id="S-3",
            persona="Frustrated User",
            rating="sideways",
            message="x",
            response_excerpt="y",
            sources=[],
        )
