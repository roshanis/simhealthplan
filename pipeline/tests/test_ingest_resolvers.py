"""Tests for per-dataset landing-page URL resolution (ingest/*.py).

Each resolver scrapes a landing page for the actual download link rather
than hard-coding a file URL. These tests exercise the resolver logic
against small, hand-trimmed HTML fixtures that mirror the *actual* anchor
markup CMS/NBER serve today (verified interactively against the live
sites during development — see manifest notes for the resolved URLs).
"""

from __future__ import annotations

from ingest import crosswalks, cpsc, landscape, mcbs, pbp_benefits, penetration

# --- Landscape ---------------------------------------------------------------

LANDSCAPE_LANDING_HTML = """
<html><body>
<a href="/files/zip/cy2026-landscape-202607.zip">CY2026 Landscape (202607) (ZIP)</a>
<a href="/files/zip/2025-congressional-district-report.zip">2025 Congressional District Report (ZIP)</a>
<a href="/files/zip/cy2006-cy2025-landscape-files.zip">CY2006-CY2025 Landscape Files (ZIP)</a>
<a href="/files/zip/2016-2024-congressional-district-reports.zip">2016-2024 Congressional District Reports (ZIP)</a>
</body></html>
"""


def test_landscape_resolves_consolidated_archive():
    url, text = landscape.resolve_download_url(html=LANDSCAPE_LANDING_HTML)
    assert url == "https://www.cms.gov/files/zip/cy2006-cy2025-landscape-files.zip"
    assert "CY2006-CY2025" in text


# --- CPSC monthly enrollment --------------------------------------------------

CPSC_2024_HTML = """
<html><body>
<a href="/files/zip/monthly-enrollment-cpsc-march-2024.zip">Monthly Enrollment by CPSC – March 2024</a>
</body></html>
"""

CPSC_2025_HTML = """
<html><body>
<a href="/files/zip/monthly-enrollment-cpsc-march-2025.zip-0">Monthly Enrollment by CPSC – March 2025</a>
</body></html>
"""


def test_cpsc_resolves_2024_url():
    url, _text = cpsc.resolve_download_url(cpsc.LANDING_PAGE_2024_03, html=CPSC_2024_HTML)
    assert url == "https://www.cms.gov/files/zip/monthly-enrollment-cpsc-march-2024.zip"


def test_cpsc_resolves_2025_url_with_drupal_suffix():
    url, _text = cpsc.resolve_download_url(cpsc.LANDING_PAGE_2025_03, html=CPSC_2025_HTML)
    assert url.endswith("monthly-enrollment-cpsc-march-2025.zip-0")


# --- MA State/County Penetration ---------------------------------------------

PENETRATION_2024_HTML = """
<html><body>
<a href="/files/zip/ma-state/county-penetration-march-2024.zip">MA State/County Penetration – March 2024</a>
</body></html>
"""

PENETRATION_2025_HTML = """
<html><body>
<a href="/files/zip/ma-state/county-penetration-march-2025.zip">MA State/County Penetration – March 2025</a>
</body></html>
"""


def test_penetration_resolves_2024_url():
    url, _text = penetration.resolve_download_url(penetration.LANDING_PAGE_2024_03, html=PENETRATION_2024_HTML)
    assert url == "https://www.cms.gov/files/zip/ma-state/county-penetration-march-2024.zip"


def test_penetration_resolves_2025_url():
    url, _text = penetration.resolve_download_url(penetration.LANDING_PAGE_2025_03, html=PENETRATION_2025_HTML)
    assert url == "https://www.cms.gov/files/zip/ma-state/county-penetration-march-2025.zip"


# --- PBP Benefits --------------------------------------------------------------

PBP_2024_Q1_HTML = """
<html><body>
<a href="/files/zip/pbp-benefits-2024-quarter-1.zip">PBP Benefits – 2024 - Quarter 1</a>
</body></html>
"""

PBP_2025_HTML = """
<html><body>
<a href="/files/zip/pbp-benefits-2025.zip">PBP Benefits - 2025</a>
</body></html>
"""


def test_pbp_benefits_resolves_2024_q1_url():
    url, _text = pbp_benefits.resolve_download_url(pbp_benefits.LANDING_PAGE_2024, html=PBP_2024_Q1_HTML)
    assert url == "https://www.cms.gov/files/zip/pbp-benefits-2024-quarter-1.zip"


def test_pbp_benefits_resolves_2025_url():
    url, _text = pbp_benefits.resolve_download_url(pbp_benefits.LANDING_PAGE_2025, html=PBP_2025_HTML)
    assert url == "https://www.cms.gov/files/zip/pbp-benefits-2025.zip"


# --- Plan crosswalk (CMS) -----------------------------------------------------

PLAN_CROSSWALK_HTML = """
<html><body>
<a href="/files/zip/plan-crosswalk-2025.zip">Plan Crosswalk 2025</a>
</body></html>
"""


def test_plan_crosswalk_resolves_url():
    url, _text = crosswalks.resolve_plan_crosswalk_url(html=PLAN_CROSSWALK_HTML)
    assert url == "https://www.cms.gov/files/zip/plan-crosswalk-2025.zip"


# --- SSA-FIPS crosswalk (NBER Apache directory index) -------------------------

NBER_DIR_LISTING_HTML = """
<html><body><table>
<tr><td><a href="orig/">orig/</a></td></tr>
<tr><td><a href="fips_state_county2025.zip">fips_state_county2025.zip</a></td></tr>
<tr><td><a href="fips_state_county_cbsa2025.csv">fips_state_county_cbsa2025.csv</a></td></tr>
<tr><td><a href="README">README</a></td></tr>
<tr><td><a href="ssa_fips_state_county_2025.csv">ssa_fips_state_county_2025.csv</a></td></tr>
<tr><td><a href="ssa_fips_state_county_2025.dta">ssa_fips_state_county_2025.dta</a></td></tr>
</table></body></html>
"""


def test_ssa_fips_resolves_csv_not_dta_or_zip():
    url, _text = crosswalks.resolve_ssa_fips_url(html=NBER_DIR_LISTING_HTML)
    assert url.endswith("ssa_fips_state_county_2025.csv")


# --- MCBS (data.cms.gov DCAT catalog, not a scraped landing page) -------------

MCBS_CATALOG_FIXTURE = {
    "dataset": [
        {
            "title": "Medicare Current Beneficiary Survey - Cost Supplement",
            "distribution": [
                {"downloadURL": "https://data.cms.gov/sites/default/files/2026-01/CSPUF2023_Data.zip"}
            ],
        },
        {
            "title": "Medicare Current Beneficiary Survey - Survey File",
            "describedBy": "https://data.cms.gov/sites/default/files/2025-11/SFPUF2023_Codebooks.zip",
            "distribution": [
                {
                    "downloadURL": "https://data.cms.gov/sites/default/files/2025-11/b76a3bff/SFPUF2023_Data.zip",
                    "title": "Medicare Current Beneficiary Survey - Survey File : 2023-01-01",
                    "temporal": "2023-01-01/2023-12-31",
                },
                {
                    "downloadURL": "https://data.cms.gov/sites/default/files/2024-10/SFPUF2022_Data.zip",
                    "title": "Medicare Current Beneficiary Survey - Survey File : 2022-10-01",
                    "temporal": "2022-01-01/2022-12-31",
                },
            ],
        },
    ]
}


def test_mcbs_resolves_latest_survey_file_and_codebook():
    result = mcbs.resolve_survey_file(catalog=MCBS_CATALOG_FIXTURE)
    assert result.data_url == "https://data.cms.gov/sites/default/files/2025-11/b76a3bff/SFPUF2023_Data.zip"
    assert result.codebook_url == "https://data.cms.gov/sites/default/files/2025-11/SFPUF2023_Codebooks.zip"
    assert "2023" in result.data_url
