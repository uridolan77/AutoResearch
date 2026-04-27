from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AR_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./autoresearch.db"
    redis_url: str = "redis://localhost:6379/0"
    data_dir: Path = Path("./data")
    worktree_root: Path = Path("./data/worktrees")
    secret_key: str = ""

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    llm_provider: Literal["anthropic", "openai"] = "anthropic"

    proposer_model: str = "claude-sonnet-4-5"
    judge_model: str = "gpt-4o-mini"

    review_timeout_hours_default: int = 48
    worktree_prune_window_default: int = 10
    validation_retry_max_default: int = 3
    max_files_per_diff_default: int = 1
    max_files_per_diff_ceiling: int = 5

    @model_validator(mode="after")
    def _validate_provider_keys(self) -> "Settings":
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError(
                "AR_ANTHROPIC_API_KEY is required when AR_LLM_PROVIDER=anthropic"
            )
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError(
                "AR_OPENAI_API_KEY is required when AR_LLM_PROVIDER=openai"
            )
        return self

    def model_post_init(self, _ctx) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.worktree_root.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
