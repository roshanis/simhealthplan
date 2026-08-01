"""Run every Phase 1 parser against the downloaded raw_cache, in dependency order.

Usage: ``uv run python -m parse.run_all`` (or ``make ingest`` from repo root,
after the download step). landscape.py must run first: crosswalks.py and
benefits.py both filter to the set of Maricopa (contract_id, plan_id,
segment_id) keys in data/interim/landscape_2024.parquet before doing any
heavy parsing.
"""

from __future__ import annotations

from parse import benefits, census_acs, cpsc, crosswalks, landscape, mcbs, penetration


def main() -> None:
    print("--- parse: landscape ---")
    df2024, df2025 = landscape.run()
    print(f"  landscape_2024: {len(df2024)} Maricopa plans")
    print(f"  landscape_2025: {len(df2025)} Maricopa plans")

    print("--- parse: cpsc ---")
    c24, c25 = cpsc.run()
    print(f"  cpsc_2024_03: {len(c24)} rows, total enrollment={c24['enrollment'].sum()}")
    print(f"  cpsc_2025_03: {len(c25)} rows, total enrollment={c25['enrollment'].sum()}")

    print("--- parse: penetration ---")
    p24, p25 = penetration.run()
    print(f"  penetration_2024_03: {p24.to_dict(orient='records')}")
    print(f"  penetration_2025_03: {p25.to_dict(orient='records')}")

    print("--- parse: crosswalks ---")
    ssa_fips, plan_cw = crosswalks.run()
    print(f"  ssa_fips_crosswalk: {len(ssa_fips)} counties")
    print(f"  plan_crosswalk_2024_2025: {len(plan_cw)} Maricopa Year-1 plans")

    print("--- parse: benefits ---")
    b24, b25 = benefits.run()
    print(f"  benefits_2024: {len(b24)} plans, coverage={benefits.coverage_rate(b24):.1%}")
    print(f"  benefits_2025: {len(b25)} plans, coverage={benefits.coverage_rate(b25):.1%}")

    print("--- parse: census_acs ---")
    acs_df = census_acs.run()
    print(f"  acs_maricopa: {len(acs_df)} variable rows")

    print("--- parse: mcbs ---")
    inventory, subset = mcbs.run()
    print(f"  mcbs_subset: {subset.shape[0]} rows x {subset.shape[1]} columns")


if __name__ == "__main__":
    main()
