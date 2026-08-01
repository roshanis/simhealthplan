"""Pipeline-wide configuration.

Loaded once as the module-level ``settings`` singleton. Values are
constants for the Maricopa County, AZ pilot (2024 -> 2025 backtest)
unless overridden via environment variables or a local ``.env`` file
(see ``pipeline/.env.example``).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# pipeline/config/settings.py -> pipeline/ -> repo root
PIPELINE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PIPELINE_DIR.parent


class Settings(BaseSettings):
    """Application settings for the Medicare Advantage simulation pipeline."""

    model_config = SettingsConfigDict(
        env_file=str(PIPELINE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Study geography & timeframe -------------------------------------
    COUNTY_FIPS: str = "04013"
    COUNTY_NAME: str = "Maricopa"
    STATE_ABBREV: str = "AZ"
    YEAR1: int = 2024
    YEAR2: int = 2025
    ENROLLMENT_MONTH: int = 3

    # --- Reproducibility ---------------------------------------------------
    SEED: int = 42

    # --- LLM configuration ---------------------------------------------------
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-5.6-luna"
    OPENAI_MODEL_REPORT: str = "gpt-5.6-luna"
    MAX_LLM_CALLS: int = 500

    # --- External data API keys ---------------------------------------------
    # Required as of 2026-05 for api.census.gov (keyless requests now 302 to
    # a "Missing Key" page). Get one at https://api.census.gov/data/key_signup.html
    CENSUS_API_KEY: str | None = None

    # --- Data directories (repo-root-relative) ------------------------------
    DATA_DIR: Path = REPO_ROOT / "data"
    RAW_CACHE_DIR: Path = REPO_ROOT / "data" / "raw_cache"
    INTERIM_DIR: Path = REPO_ROOT / "data" / "interim"
    PROCESSED_DIR: Path = REPO_ROOT / "data" / "processed"
    LLM_CACHE_DIR: Path = REPO_ROOT / "data" / "cache" / "llm"
    SHARED_GOLDEN_DIR: Path = REPO_ROOT / "shared" / "golden"


settings = Settings()
