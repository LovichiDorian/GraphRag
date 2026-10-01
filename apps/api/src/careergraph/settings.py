"""Typed runtime configuration (12-factor: everything comes from the environment)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    environment: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    # ── LLM (Gemini Developer API, or Vertex AI express mode) ────────────────
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY")
    )
    google_genai_use_vertexai: bool = False
    # Ordered fallback chains: the first healthy model wins, a circuit breaker
    # skips models that recently returned 429/5xx.
    chat_models: CsvList = [
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]
    fast_models: CsvList = [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ]
    extraction_models: CsvList = [
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.5-flash-lite",
    ]
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 768
    llm_timeout_s: float = 90.0
    circuit_open_s: float = 60.0
    llm_daily_budget: int = 3000

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("localdevpassword")
    neo4j_database: str = "neo4j"

    # ── Knowledge sources ─────────────────────────────────────────────────────
    data_dir: Path = Path("data")
    cache_dir: Path = Path(".cache/careergraph")
    github_user: str | None = None  # defaults to profile.yaml → github.user
    github_token: SecretStr | None = None
    github_include_private: bool = False
    github_include_forks: bool = False
    github_repos_include: CsvList = []
    github_repos_exclude: CsvList = []
    github_local_dir: Path | None = None  # dev/offline: read repositories from local clones

    # ── HTTP API ──────────────────────────────────────────────────────────────
    public_url: str = "http://localhost:3000"
    cors_origins: CsvList = ["http://localhost:3000"]
    rate_limit_per_minute: int = 8
    rate_limit_per_day: int = 80
    max_question_chars: int = 1500
    max_history_messages: int = 8
    max_job_description_chars: int = 15000
    answer_cache_ttl_s: int = 24 * 3600
    warm_cache: bool = True  # pre-compute answers to the starter questions (quota friendly)
    graph_refresh_s: int = 120

    @field_validator(
        "chat_models",
        "fast_models",
        "extraction_models",
        "cors_origins",
        "github_repos_include",
        "github_repos_exclude",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("gemini_api_key", "github_token", mode="before")
    @classmethod
    def _empty_secret_is_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_api_key.get_secret_value())

    @property
    def profile_path(self) -> Path:
        return self.data_dir / "profile.yaml"

    @property
    def notes_dir(self) -> Path:
        return self.data_dir / "notes"


@lru_cache
def get_settings() -> Settings:
    return Settings()
