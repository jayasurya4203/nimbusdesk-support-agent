"""Application configuration.

Every tunable escalation, retrieval, and model setting can be overridden with an
environment variable documented in README.md and .env.example.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean, got {raw!r}")


def _env_path(name: str, default: str) -> Path:
    path = Path(_env_str(name, default)).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings, loaded once from the environment."""

    gemini_api_key: str = ""
    chat_model: str = "gemini-2.5-flash"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 32
    max_retries: int = 4
    retry_base_delay_s: float = 1.5

    data_dir: Path = PROJECT_ROOT / "data"
    chroma_dir: Path = PROJECT_ROOT / "chroma_db"
    collection_name: str = "nimbusdesk_kb"
    handoff_dir: Path = PROJECT_ROOT / "handoffs"
    feedback_file: Path = PROJECT_ROOT / "feedback" / "feedback.jsonl"

    chunk_size: int = 900
    chunk_overlap: int = 150
    top_k: int = 4
    candidate_k: int = 15
    min_retrieval_similarity: float = 0.52
    min_supporting_chunks: int = 1
    enable_lexical_rerank: bool = True
    lexical_weight: float = 0.18
    require_citations: bool = True

    max_turns_before_escalation: int = 6
    frustration_streak_threshold: int = 2
    frustration_score_threshold: float = 0.6
    sensitive_mode: str = "actions_only"
    extra_sensitive_terms: tuple[str, ...] = ()

    @property
    def has_api_key(self) -> bool:
        return bool(self.gemini_api_key)

    def require_api_key(self) -> str:
        if not self.gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add a key from "
                "https://aistudio.google.com/apikey, then restart the app."
            )
        return self.gemini_api_key

    def with_overrides(self, **kwargs: object) -> "Settings":
        """Return a copy with validated overrides (used by the UI controls)."""
        updated = replace(self, **kwargs)
        updated._validate()
        return updated

    def _validate(self) -> None:
        if self.sensitive_mode not in {"actions_only", "always"}:
            raise ConfigurationError(
                "SENSITIVE_ESCALATION_MODE must be 'actions_only' or 'always'"
            )
        if not 0.0 <= self.min_retrieval_similarity <= 1.0:
            raise ConfigurationError("MIN_RETRIEVAL_SIMILARITY must be between 0 and 1")
        if not 0.0 <= self.frustration_score_threshold <= 1.0:
            raise ConfigurationError("FRUSTRATION_SCORE_THRESHOLD must be between 0 and 1")
        if self.top_k < 1 or self.candidate_k < self.top_k:
            raise ConfigurationError("CANDIDATE_K must be >= TOP_K >= 1")
        if self.chunk_overlap >= self.chunk_size:
            raise ConfigurationError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Settings":
        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
        settings = cls(
            gemini_api_key=_env_str("GEMINI_API_KEY", ""),
            chat_model=_env_str("CHAT_MODEL", "gemini-2.5-flash"),
            embedding_model=_env_str("EMBEDDING_MODEL", "gemini-embedding-001"),
            embedding_dimensions=_env_int("EMBEDDING_DIMENSIONS", 768),
            embedding_batch_size=_env_int("EMBEDDING_BATCH_SIZE", 32),
            max_retries=_env_int("MAX_RETRIES", 4),
            retry_base_delay_s=_env_float("RETRY_BASE_DELAY_S", 1.5),
            data_dir=_env_path("DATA_DIR", "data"),
            chroma_dir=_env_path("CHROMA_DIR", "chroma_db"),
            collection_name=_env_str("COLLECTION_NAME", "nimbusdesk_kb"),
            handoff_dir=_env_path("HANDOFF_DIR", "handoffs"),
            feedback_file=_env_path("FEEDBACK_FILE", "feedback/feedback.jsonl"),
            chunk_size=_env_int("CHUNK_SIZE", 900),
            chunk_overlap=_env_int("CHUNK_OVERLAP", 150),
            top_k=_env_int("TOP_K", 4),
            candidate_k=_env_int("CANDIDATE_K", 15),
            min_retrieval_similarity=_env_float("MIN_RETRIEVAL_SIMILARITY", 0.52),
            min_supporting_chunks=_env_int("MIN_SUPPORTING_CHUNKS", 1),
            enable_lexical_rerank=_env_bool("ENABLE_LEXICAL_RERANK", True),
            lexical_weight=_env_float("LEXICAL_WEIGHT", 0.18),
            require_citations=_env_bool("REQUIRE_CITATIONS", True),
            max_turns_before_escalation=_env_int("MAX_TURNS_BEFORE_ESCALATION", 6),
            frustration_streak_threshold=_env_int("FRUSTRATION_STREAK_THRESHOLD", 2),
            frustration_score_threshold=_env_float("FRUSTRATION_SCORE_THRESHOLD", 0.6),
            sensitive_mode=_env_str("SENSITIVE_ESCALATION_MODE", "actions_only"),
            extra_sensitive_terms=_env_list("EXTRA_SENSITIVE_TERMS"),
        )
        settings._validate()
        return settings
