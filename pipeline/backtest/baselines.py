"""Phase 5 naive baselines: no_change and trend, both mapped through the
2024->2025 crosswalk onto 2025 plan keys.

Both baselines reuse ``choice_model.predict.map_prior_year1_to_year2`` for
the crosswalk traversal itself (renewed/renumbered/consolidated ->
successor key, terminated -> ``NO_SUCCESSOR_BUCKET``) -- that function is
generic over what "mass" means (an archetype's Year-1 prior probability
there, a plan's 2024 *share* here), so no crosswalk-walking logic is
reimplemented; only the post-mapping renormalization step is new, and it's
a documented deliberate choice, not incidental:

  * **no_change**: predicted 2025 share = actual 2024 share. A terminated
    plan has no 2025 row to hold its share, so (per the Phase 5 spec) that
    mass is redistributed **proportionally** across every surviving plan +
    the outside option, in proportion to their own already-mapped 2024
    share. Concretely: drop ``NO_SUCCESSOR_BUCKET``, then divide every
    remaining key by ``(1 - terminated_share)`` so the result sums back to
    1.0. This is mathematically the same operation as
    ``choice_sets.renormalize_prior_plan``'s "drop ineligible mass,
    renormalize the rest proportionally" rule, just without needing a
    per-archetype eligibility filter (every 2025 plan is "eligible" for
    this aggregate, non-archetype baseline).
  * **trend**: per-2024-plan linear extrapolation
    ``clip(share_2024 + (share_2024 - share_2023), min=0)``, renormalized
    to sum to 1 over the *2024* key space, THEN mapped through the same
    crosswalk-and-proportional-redistribution as no_change. The 2023 share
    is looked up against the same 2024 landscape-plan universe (contract_id
    + plan_id assumed stable 2023->2024 -- there is no CMS 2023->2024 plan
    crosswalk in this pipeline, so a plan that changed IDs between 2023 and
    2024 is conservatively treated as "new in 2024" (2023 share 0.0), the
    same conservative default ``choice_model/predict.py`` uses for any
    crosswalk-unmapped key). The 2023 share denominator uses
    ``settings.YEAR1``'s (2024) eligibles total rather than a genuine 2023
    eligibles count -- this pipeline never ingests a March 2023 penetration
    file (only CPSC), so county-wide MA-eligible population growth between
    March 2023 and March 2024 is assumed negligible for this one-year,
    single-county window. Documented here and surfaced in
    ``run_backtest.py``'s output metadata, not silently assumed.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd

from choice_model import predict
from config.settings import settings
from ingest import cpsc as cpsc_ingest
from ingest.base import DownloadRecord
from parse import cpsc as cpsc_parse

CPSC_2023_LABEL = "2023_03"
CPSC_2023_YEAR_MONTH = "2023-03"
CPSC_2023_INTERIM_FILENAME = "cpsc_2023_03.parquet"


# --- crosswalk mapping (shared by both baselines) -----------------------------------


def _map_2024_share_to_2025(
    share_2024: dict[str, float],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str,
    outside_key_year2: str,
) -> dict[str, float]:
    """Crosswalk-map a 2024-keyed share distribution onto 2025 keys, then
    drop the terminated-plan (``NO_SUCCESSOR_BUCKET``) mass and renormalize
    the remainder proportionally so the result sums back to 1.0 -- see
    module docstring for why this is the documented no_change/trend
    redistribution rule."""
    mapped = predict.map_prior_year1_to_year2(share_2024, crosswalk_map, outside_key_year1, outside_key_year2)
    mapped.pop(predict.NO_SUCCESSOR_BUCKET, None)
    survivor_total = sum(mapped.values())
    if survivor_total <= 0:
        return mapped
    return {key: value / survivor_total for key, value in mapped.items()}


# --- no_change ------------------------------------------------------------------------


def no_change_baseline(
    share_2024: dict[str, float],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str = predict.OUTSIDE_KEY_YEAR1,
    outside_key_year2: str = predict.OUTSIDE_KEY_YEAR2,
) -> dict[str, float]:
    """Predicted 2025 share = actual 2024 share, crosswalk-mapped onto 2025
    keys with terminated-plan share redistributed proportionally (see
    module docstring). ``share_2024`` must be a full 2024-keyed share
    distribution (plan keys + ``outside_key_year1``) summing to 1.0."""
    return _map_2024_share_to_2025(share_2024, crosswalk_map, outside_key_year1, outside_key_year2)


# --- trend --------------------------------------------------------------------------


def _linear_extrapolate_and_renormalize(share_2024: dict[str, float], share_2023: dict[str, float]) -> dict[str, float]:
    keys = set(share_2024) | set(share_2023)
    raw = {key: max(0.0, share_2024.get(key, 0.0) + (share_2024.get(key, 0.0) - share_2023.get(key, 0.0))) for key in keys}
    total = sum(raw.values())
    if total <= 0:
        return raw
    return {key: value / total for key, value in raw.items()}


def trend_baseline(
    share_2024: dict[str, float],
    share_2023: dict[str, float],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str = predict.OUTSIDE_KEY_YEAR1,
    outside_key_year2: str = predict.OUTSIDE_KEY_YEAR2,
) -> dict[str, float]:
    """Predicted 2025 share via per-plan linear extrapolation from the
    2023->2024 share change, clipped at 0, renormalized over the 2024 key
    space, then crosswalk-mapped onto 2025 keys (same proportional
    terminated-share redistribution as ``no_change_baseline``). Both
    ``share_2024`` and ``share_2023`` are 2024-keyed distributions (see
    module docstring for the 2023 key-matching / denominator assumptions)."""
    trend_2024_keyed = _linear_extrapolate_and_renormalize(share_2024, share_2023)
    return _map_2024_share_to_2025(trend_2024_keyed, crosswalk_map, outside_key_year1, outside_key_year2)


# --- 2023 CPSC ingest/parse (on-demand, not part of `make ingest`) ------------------


def ensure_cpsc_2023_ingested(client: httpx.Client | None = None, force: bool = False) -> DownloadRecord:
    """Cache-first download of the March 2023 CPSC file via the existing
    ingest framework (browser UA, manifest-logged) -- see
    ``ingest/cpsc.py``'s ``LANDING_PAGE_2023_03`` docstring for why this
    isn't wired into ``ingest_all()``/`make ingest`. Raises the same
    exceptions ``ingest.cpsc.ingest`` would (e.g. ``RuntimeError`` if CMS's
    legacy landing page no longer has a matching zip link, or an
    ``httpx``/network error) -- callers (``run_backtest.py``) decide how to
    degrade when that happens.
    """
    return cpsc_ingest.ingest(cpsc_ingest.LANDING_PAGE_2023_03, CPSC_2023_LABEL, client=client, force=force)


def load_or_parse_cpsc_2023() -> pd.DataFrame:
    """Parses (and caches to ``data/interim/cpsc_2023_03.parquet``) the
    already-downloaded March 2023 CPSC zip, via the existing generic
    ``parse.cpsc.parse_zip`` (same suppression handling, same Maricopa FIPS
    filter as every other CPSC year -- not reimplemented). Requires
    ``ensure_cpsc_2023_ingested()`` to have succeeded first (raises
    ``FileNotFoundError`` via ``parse.cpsc``'s own cached-zip lookup
    otherwise).
    """
    interim_path = settings.INTERIM_DIR / CPSC_2023_INTERIM_FILENAME
    if interim_path.exists():
        return pd.read_parquet(interim_path)

    zip_path = _find_cached_2023_zip()
    df = cpsc_parse.parse_zip(zip_path, settings.COUNTY_FIPS, CPSC_2023_YEAR_MONTH)

    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(interim_path, index=False)
    return df


def _find_cached_2023_zip() -> Path:
    # Deliberately reuses parse.cpsc's private cached-zip lookup (same
    # "<label>__*.zip*" glob convention every other CPSC year uses) rather
    # than re-deriving the glob pattern here.
    return cpsc_parse._find_cached_zip(CPSC_2023_LABEL)  # noqa: SLF001
