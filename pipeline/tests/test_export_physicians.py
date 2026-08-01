"""Tests for export_artifacts.build_physicians — the personas-style
available-flag contract for the physician-supply artifact."""

from __future__ import annotations

from export.export_artifacts import build_physicians


def test_build_physicians_absent_file_exports_unavailable_placeholder():
    out = build_physicians(None)
    assert out == {
        "available": False,
        "totals": None,
        "top_specialties": [],
        "top_organizations": [],
    }


def test_build_physicians_present_file_passes_through_with_available_flag():
    processed = {
        "metadata": {"county_fips": "04013", "network_linkage": False},
        "totals": {
            "clinicians": 3,
            "organizations": 2,
            "practice_locations": 4,
            "specialties": 2,
            "telehealth_share": 0.5,
        },
        "top_specialties": [{"specialty": "INTERNAL MEDICINE", "clinicians": 2}],
        "top_organizations": [{"org_name": "BANNER HEALTH", "clinicians": 2}],
    }
    out = build_physicians(processed)

    assert out["available"] is True
    assert out["totals"]["clinicians"] == 3
    assert out["metadata"]["network_linkage"] is False
    assert out["top_specialties"] == processed["top_specialties"]
    assert out["top_organizations"] == processed["top_organizations"]
