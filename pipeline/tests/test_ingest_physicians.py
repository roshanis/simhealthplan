"""Tests for ingest/physicians.py URL resolution.

The DAC file URL is resolved from the Provider Data Catalog's metastore API
(a JSON interface -- the dataset pages are a JS app with no scrapeable
anchors); the ZCTA->county file from Census's plain rel2020 directory index.
Fixtures mirror the actual shapes served today.
"""

from __future__ import annotations

import pytest

from ingest import physicians

# The DKAN catalog's current metastore shape: distribution[].data.downloadURL.
METASTORE_NESTED = """
{
  "identifier": "mj5m-pzi6",
  "title": "National Downloadable File",
  "distribution": [
    {
      "identifier": "abc-123",
      "data": {
        "title": "National Downloadable File",
        "downloadURL": "https://data.cms.gov/provider-data/sites/default/files/resources/deadbeef_20260701/DAC_NationalDownloadableFile.csv",
        "mediaType": "text/csv"
      }
    }
  ]
}
"""

# The flat shape older DKAN releases served: distribution[].downloadURL.
METASTORE_FLAT = """
{
  "identifier": "mj5m-pzi6",
  "distribution": [
    {
      "downloadURL": "https://data.cms.gov/provider-data/sites/default/files/resources/cafef00d_20260101/DAC_NationalDownloadableFile.csv"
    }
  ]
}
"""

ZCTA_DIRECTORY_HTML = """
<html><body><pre>
<a href="tab20_zcta520_county20_natl.txt">tab20_zcta520_county20_natl.txt</a>
<a href="tab20_zcta520_cousub20_natl.txt">tab20_zcta520_cousub20_natl.txt</a>
<a href="tab20_zcta520_place20_natl.txt">tab20_zcta520_place20_natl.txt</a>
</pre></body></html>
"""


def test_resolve_dac_url_from_nested_distribution():
    url = physicians.resolve_dac_url(metastore_json=METASTORE_NESTED)
    assert url.endswith("DAC_NationalDownloadableFile.csv")
    assert url.startswith("https://data.cms.gov/")


def test_resolve_dac_url_from_flat_distribution():
    url = physicians.resolve_dac_url(metastore_json=METASTORE_FLAT)
    assert "cafef00d" in url


def test_resolve_dac_url_raises_on_empty_distribution():
    with pytest.raises(RuntimeError, match="mj5m-pzi6"):
        physicians.resolve_dac_url(metastore_json='{"distribution": []}')


def test_resolve_zcta_county_url_picks_county_file_only():
    url, text = physicians.resolve_zcta_county_url(html=ZCTA_DIRECTORY_HTML)
    assert url == (
        "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
        "tab20_zcta520_county20_natl.txt"
    )
    assert "county20" in text
