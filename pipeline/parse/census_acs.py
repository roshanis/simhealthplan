"""Parse: Census ACS 5-year (2018-2022 vintage) tables for Maricopa County (04013).

Source: ``data/raw_cache/acs/acsdt5y2022-<table>.dat`` (national, pipe-delimited,
one row per U.S. geography) + ``ACS20225YR_Table_Shells.txt`` (variable code ->
label). See ingest/census_acs.py for why this keyless flat-file route is the
primary method (api.census.gov requires a key as of 2026-05).

Each .dat file is large (tens to hundreds of MB, every geography in the
country) so we never load it into a DataFrame — ``find_geo_row`` streams the
file line-by-line and returns only Maricopa County's row
(GEO_ID == "0500000US04013").

Each data column pair is named ``<TABLE>_E<NNN>`` (estimate) /
``<TABLE>_M<NNN>`` (margin of error); the table shells file's "Unique ID"
column uses the un-prefixed form ``<TABLE>_<NNN>`` as the join key for
labels. Census encodes "not applicable / not computed" as large sentinel
values (e.g. -555555555 for margin of error on a derived aggregate,
-222222222 for insufficient sample); any value with |v| >= 111111111 is
treated as null since no single-county ACS estimate legitimately reaches
that magnitude.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd

from config.settings import settings
from ingest.census_acs import MARICOPA_GEO_ID, TABLES

DATASET = "acs"

EXPECTED_COLUMNS = [
    "table_id",
    "variable_code",
    "line",
    "label",
    "title",
    "universe",
    "estimate",
    "margin_of_error",
]

_NULL_SENTINEL_THRESHOLD = 111_111_111
_VAR_RE = re.compile(r"^(?P<table>[A-Z0-9]+)_E(?P<line>\d+)$")


def is_census_null_sentinel(value: int) -> bool:
    return abs(value) >= _NULL_SENTINEL_THRESHOLD


def _to_int_or_none(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    return None if is_census_null_sentinel(v) else v


def find_geo_row(path: Path, geo_id: str) -> tuple[list[str], list[str]]:
    """Stream ``path`` and return (header, values) for the row whose GEO_ID
    matches exactly. Raises RuntimeError if not found. Streaming keeps peak
    memory low even for the ~200MB national files."""
    with open(path, "r", encoding="utf-8-sig") as f:
        header = f.readline().rstrip("\n").split("|")
        prefix = geo_id + "|"
        for line in f:
            if line.startswith(prefix):
                return header, line.rstrip("\n").split("|")
    raise RuntimeError(f"GEO_ID {geo_id!r} not found in {path}")


def load_table_shells(raw_bytes: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw_bytes), sep="|", dtype=str, encoding="utf-8-sig")


def tidy_table(table: str, header: list[str], values: list[str], shells: pd.DataFrame) -> pd.DataFrame:
    row = dict(zip(header, values))
    shells_by_id = shells.set_index("Unique ID")

    records = []
    for col in header:
        m = _VAR_RE.match(col)
        if not m or m.group("table").lower() != table.lower():
            continue
        line_num = m.group("line")
        var_code = f"{m.group('table')}_{line_num}"
        m_col = f"{m.group('table')}_M{line_num}"

        estimate = _to_int_or_none(row.get(col, ""))
        margin = _to_int_or_none(row.get(m_col, "")) if m_col in row else None

        if var_code in shells_by_id.index:
            shell = shells_by_id.loc[var_code]
            label, title, universe = shell["Label"], shell["Title"], shell["Universe"]
        else:
            label, title, universe = None, None, None

        records.append(
            {
                "table_id": m.group("table"),
                "variable_code": var_code,
                "line": int(float(line_num)) if line_num.replace(".", "", 1).isdigit() else line_num,
                "label": label,
                "title": title,
                "universe": universe,
                "estimate": estimate,
                "margin_of_error": margin,
            }
        )
    return pd.DataFrame.from_records(records, columns=EXPECTED_COLUMNS)


def run() -> pd.DataFrame:
    shells_path = settings.RAW_CACHE_DIR / DATASET / "ACS20225YR_Table_Shells.txt"
    shells = load_table_shells(shells_path.read_bytes())

    frames = []
    for table in TABLES:
        dat_path = settings.RAW_CACHE_DIR / DATASET / f"acsdt5y2022-{table}.dat"
        header, values = find_geo_row(dat_path, MARICOPA_GEO_ID)
        frames.append(tidy_table(table, header, values, shells))

    out = pd.concat(frames, ignore_index=True)
    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(settings.INTERIM_DIR / "acs_maricopa.parquet", index=False)
    return out


if __name__ == "__main__":
    df = run()
    print(f"acs_maricopa: {len(df)} variable rows across tables {TABLES}")
