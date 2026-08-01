"""Run every Phase 1 ingest step, cache-first and idempotent.

Usage: ``uv run python -m ingest.run_all``  (or ``make ingest`` from repo root).

Each dataset's ``ingest()``/``ingest_all()`` skips the network call entirely
when the destination file already exists in data/raw_cache/ (see
ingest/base.py's ``download_file``), so re-running this is always safe and
cheap once the cache is warm.
"""

from __future__ import annotations

from ingest import census_acs, cpsc, crosswalks, landscape, mcbs, pbp_benefits, penetration


def main() -> None:
    steps = [
        ("landscape", landscape.ingest),
        ("cpsc", cpsc.ingest_all),
        ("penetration", penetration.ingest_all),
        ("pbp_benefits", pbp_benefits.ingest_all),
        ("crosswalks", crosswalks.ingest_all),
        ("mcbs", mcbs.ingest),
        ("census_acs", census_acs.ingest),
    ]
    for name, fn in steps:
        print(f"--- ingest: {name} ---")
        result = fn()
        if isinstance(result, list):
            for record in result:
                print(f"  {record.filename}: {'cached' if record.skipped_cached else 'downloaded'} ({record.bytes:,} bytes)")
        else:
            print(f"  {result.filename}: {'cached' if result.skipped_cached else 'downloaded'} ({result.bytes:,} bytes)")


if __name__ == "__main__":
    main()
