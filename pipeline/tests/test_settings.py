"""Tests for pipeline configuration settings.

TDD: written before config/settings.py exists — expected to fail on
import until the Settings class is implemented.
"""

from pathlib import Path

from config.settings import settings


def test_settings_load():
    """Settings module loads and exposes a `settings` instance."""
    assert settings is not None


def test_county_fips_correct():
    assert settings.COUNTY_FIPS == "04013"
    assert settings.COUNTY_NAME == "Maricopa"
    assert settings.STATE_ABBREV == "AZ"


def test_seed_fixed():
    assert settings.SEED == 42


def test_year_config():
    assert settings.YEAR1 == 2024
    assert settings.YEAR2 == 2025
    assert settings.ENROLLMENT_MONTH == 3


def test_llm_config_defaults():
    assert settings.OPENAI_MODEL == "gpt-5.6-luna"
    assert settings.OPENAI_MODEL_REPORT == "gpt-5.6-luna"
    assert settings.MAX_LLM_CALLS == 500


def test_data_paths_resolve():
    """Data directory paths are absolute, repo-root-relative Path objects."""
    for attr in (
        "DATA_DIR",
        "RAW_CACHE_DIR",
        "INTERIM_DIR",
        "PROCESSED_DIR",
        "LLM_CACHE_DIR",
    ):
        path = getattr(settings, attr)
        assert isinstance(path, Path)
        assert path.is_absolute()

    # Sanity check the hierarchy is anchored under the repo-root data/ dir.
    assert settings.RAW_CACHE_DIR == settings.DATA_DIR / "raw_cache"
    assert settings.INTERIM_DIR == settings.DATA_DIR / "interim"
    assert settings.PROCESSED_DIR == settings.DATA_DIR / "processed"
    assert settings.LLM_CACHE_DIR == settings.DATA_DIR / "cache" / "llm"
