"""Generates the Python <-> TypeScript golden parity fixture for the Phase 3
multinomial-logit choice model.

Writes ``shared/golden/parity_fixture.json``: a self-contained, deterministic
snapshot built from the real committed artifacts (``data/processed/
coefficients.json``'s ``base_coefficients``, ``data/processed/
archetypes.json``, ``data/processed/plans_2025.json``) plus hand-picked
synthetic edge-case archetypes and plan-attribute scenario variants, with
expected per-plan choice probabilities computed by the frozen
``choice_model.choice_sets`` / ``choice_model.utility`` modules -- the parity
source of truth the TypeScript port under ``app/src/lib/choice-model/``
must reproduce (see ``app/tests/parity.test.ts``).

Every float in this file is written at full float64 precision: Python's
``json`` module serializes floats via ``repr(float)``, the shortest decimal
string that round-trips to the exact same IEEE-754 double, so the
TypeScript side can compare against the precise values this module produced
rather than a rounded approximation.

Fixture schema::

    {
      "metadata": {...deterministic provenance/documentation, no data a
                    consumer needs to function...},
      "base_coefficients": {"b_premium": ..., ...},   # 9 floats
      "plans": [...the full data/processed/plans_2025.json `plans` array,
                 unmodified -- the shared "pristine" plan universe every
                 case's plan list is derived from...],
      "cases": [
        {
          "case_id": str,
          "kind": "real" | "synthetic" | "scenario",
          "description": str,
          "archetype": {...id/age_band/attitude_segment/dual_proxy/
                         prior_plan_year1, plus whatever other
                         archetypes.json fields this archetype has...},
          "plan_patches": {plan_key: {field: new_value, ...}, ...},
          "plan_subset": [plan_key, ...] | null,
          "expected_probabilities": {plan_key_or_outside_key: float, ...},
        },
        ...
      ],
    }

A case's actual plan list is derived from the top-level ``plans`` array by
(1) applying ``plan_patches`` (shallow field overrides, keyed by
``plan_key``) and then (2) restricting to ``plan_subset`` if it is not
``null``. This two-step derivation is itself part of the parity contract:
both ``pipeline/tests/test_golden_parity.py`` and ``app/tests/parity.test.ts``
replay it independently of this module's internal case-building helpers.

Regenerate with::

    cd pipeline && uv run python -m export.golden_fixture
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from choice_model import choice_sets, utility
from config.settings import settings

OUTSIDE_KEY = "other_or_no_ma_2024"

# 12 hand-picked archetypes.json `id`s, covering all 5 attitude segments
# (the 4 SEGMENT_MULTIPLIERS-named segments plus the "mixed" catch-all/
# identity segment), dual_proxy True and False, and age_band == "85+"
# (the I-SNP eligibility proxy) crossed with both dual_proxy (D-SNP+I-SNP
# overlap) and health_status_driven (I-SNP+C-SNP overlap). Order is the
# fixture's case order -- a fixed explicit list (not derived from
# archetypes.json's array order) so regeneration stays deterministic even
# if that file's internal ordering ever changes.
REAL_ARCHETYPE_IDS: list[str] = [
    "a65_69-higher-hispanic-price_sensitive",
    "a65_69-low-white-benefit_maximizer",
    "a65_69-middle-white-brand_loyal",
    "a70_74-higher-white-price_sensitive",
    "a70_74-middle-hispanic-brand_loyal",
    "a70_74-low-white-health_status_driven",
    "a75_84-higher-mixed-mixed",
    "a75_84-low-hispanic-price_sensitive",
    "a75_84-middle-hispanic-health_status_driven",
    "a85_plus-higher-white-health_status_driven",
    "a85_plus-low-mixed-mixed",
    "a85_plus-middle-white-benefit_maximizer",
]

# Both are dual_proxy == True (see REAL_ARCHETYPE_IDS above), so both are
# eligible for the largest-by-enrollment plan below, which is a D-SNP --
# without that, the scenario patch (premium/dental change) would land on a
# plan outside the archetype's choice set and be invisible in the output.
SCENARIO_PREMIUM_ARCHETYPE_ID = "a75_84-low-hispanic-price_sensitive"
SCENARIO_DENTAL_ARCHETYPE_ID = "a65_69-low-white-benefit_maximizer"

PREMIUM_DELTA = -15.0

# Optional archetypes.json fields copied through verbatim when present (real
# archetypes have all of these; synthetic ones only carry the fields the
# choice model actually consumes).
ARCHETYPE_OPTIONAL_FIELDS = ("income_tier", "race_eth", "share_of_population", "weight", "traits")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _json_safe(value):
    """Recursively replace NaN/Infinity floats with None.

    Python's ``json`` module happily serializes ``float('nan')`` as the bare
    token ``NaN`` (a non-standard extension, ``allow_nan=True`` by default)
    -- and a handful of ``plans_2025.json`` records do have a NaN
    ``deductible`` (a genuine upstream data gap, not a bug). That token
    isn't valid JSON per RFC 8259, so strict parsers -- including
    JavaScript's ``JSON.parse``, which the TypeScript parity test uses --
    reject it outright. ``deductible`` isn't read anywhere in the choice
    model (see utility.py's ``plan_utility``), so replacing it with ``null``
    here costs nothing functionally while keeping this fixture valid,
    portable JSON.
    """
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, dict):
        return {key: _json_safe(v) for key, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _archetype_record(archetype: dict) -> dict:
    record = {
        "id": archetype["id"],
        "age_band": archetype["age_band"],
        "attitude_segment": archetype["attitude_segment"],
        "dual_proxy": archetype["dual_proxy"],
        "prior_plan_year1": archetype["prior_plan_year1"],
    }
    for field in ARCHETYPE_OPTIONAL_FIELDS:
        if field in archetype:
            record[field] = archetype[field]
    return record


def _apply_plan_patches(plans: list[dict], plan_patches: dict[str, dict]) -> list[dict]:
    return [({**plan, **plan_patches[plan["plan_key"]]} if plan["plan_key"] in plan_patches else plan) for plan in plans]


def _apply_plan_subset(plans: list[dict], plan_subset: list[str] | None) -> list[dict]:
    if plan_subset is None:
        return plans
    subset = set(plan_subset)
    return [plan for plan in plans if plan["plan_key"] in subset]


def resolve_case_plans(plans: list[dict], plan_patches: dict[str, dict], plan_subset: list[str] | None) -> list[dict]:
    """Derive one case's actual plan list from the fixture's pristine
    top-level `plans` array: patch, then (optionally) subset.

    Exposed (not just inlined) because pipeline/tests/test_golden_parity.py
    replays exactly this derivation from the committed fixture's own JSON
    fields, independent of this module's other build_fixture() internals --
    that's the same derivation app/tests/parity.test.ts's TS replay performs.
    """
    return _apply_plan_subset(_apply_plan_patches(plans, plan_patches), plan_subset)


def _synthetic_archetypes(plans: list[dict]) -> list[dict]:
    single_eligible_plan_key = next(p["plan_key"] for p in plans if p["snp_type"] == choice_sets.NOT_APPLICABLE_SNP_TYPE)

    return [
        {
            "id": "synthetic_zero_prior_mass",
            "age_band": "70-74",
            "attitude_segment": "mixed",
            "dual_proxy": False,
            "prior_plan_year1": {},
            "_plan_subset": None,
            "_description": (
                "No Year-1 prior at all (empty prior_plan_year1): every inertia term "
                "defaults to 0.0, exercising the b_inertia * 0.0 path for every plan "
                "and the outside option alike."
            ),
        },
        {
            "id": "synthetic_all_mass_outside",
            "age_band": "75-84",
            "attitude_segment": "price_sensitive",
            "dual_proxy": False,
            "prior_plan_year1": {OUTSIDE_KEY: 1.0},
            "_plan_subset": None,
            "_description": (
                "All Year-1 prior mass sits on the outside option, none on any plan: "
                "maximizes the inertia pull toward the outside option and exercises "
                "renormalize_prior_plan's already-normalized (no-op) path."
            ),
        },
        {
            "id": "synthetic_single_plan_eligible",
            "age_band": "65-69",
            "attitude_segment": "benefit_maximizer",
            "dual_proxy": False,
            "prior_plan_year1": {single_eligible_plan_key: 0.6, OUTSIDE_KEY: 0.4},
            "_plan_subset": [single_eligible_plan_key],
            "_description": (
                "Choice set restricted (via plan_subset) to exactly one eligible plan "
                f"({single_eligible_plan_key}) plus the always-eligible outside option: "
                "the degenerate two-way softmax."
            ),
        },
    ]


def _build_case(
    *,
    case_id: str,
    kind: str,
    description: str,
    archetype: dict,
    plans: list[dict],
    base_coefficients: dict[str, float],
    plan_patches: dict[str, dict],
    plan_subset: list[str] | None,
) -> dict:
    case_plans = resolve_case_plans(plans, plan_patches, plan_subset)

    eligible = choice_sets.eligible_plans(archetype, case_plans)
    renormalized_prior = choice_sets.renormalize_prior_plan(
        archetype.get("prior_plan_year1", {}), archetype, case_plans, OUTSIDE_KEY
    )
    expected_probabilities = utility.choice_probabilities(
        base_coefficients, archetype["attitude_segment"], eligible, renormalized_prior, OUTSIDE_KEY
    )

    return {
        "case_id": case_id,
        "kind": kind,
        "description": description,
        "archetype": _archetype_record(archetype),
        "plan_patches": plan_patches,
        "plan_subset": plan_subset,
        "expected_probabilities": expected_probabilities,
    }


def build_fixture() -> dict:
    """Build the fixture dict in memory (no file I/O beyond reading the real
    committed artifacts). Pure given those artifacts' contents: no random
    seeds, no dict/set-ordering-dependent traversal of anything that isn't
    itself already deterministically ordered."""
    coefficients = _load_json(settings.PROCESSED_DIR / "coefficients.json")
    base_coefficients = coefficients["base_coefficients"]

    archetypes_by_id = {a["id"]: a for a in _load_json(settings.PROCESSED_DIR / "archetypes.json")["archetypes"]}
    plans = _load_json(settings.PROCESSED_DIR / f"plans_{settings.YEAR2}.json")["plans"]

    cases: list[dict] = []

    for archetype_id in REAL_ARCHETYPE_IDS:
        archetype = archetypes_by_id[archetype_id]
        cases.append(
            _build_case(
                case_id=f"real__{archetype_id}",
                kind="real",
                description=(
                    f"Real archetype {archetype_id} (segment={archetype['attitude_segment']}, "
                    f"dual_proxy={archetype['dual_proxy']}, age_band={archetype['age_band']}) "
                    f"against the full {settings.YEAR2} plan list."
                ),
                archetype=archetype,
                plans=plans,
                base_coefficients=base_coefficients,
                plan_patches={},
                plan_subset=None,
            )
        )

    for synthetic in _synthetic_archetypes(plans):
        description = synthetic.pop("_description")
        plan_subset = synthetic.pop("_plan_subset")
        cases.append(
            _build_case(
                case_id=f"synthetic__{synthetic['id']}",
                kind="synthetic",
                description=description,
                archetype=synthetic,
                plans=plans,
                base_coefficients=base_coefficients,
                plan_patches={},
                plan_subset=plan_subset,
            )
        )

    enrollment_field = f"enrollment_{settings.YEAR2}_{settings.ENROLLMENT_MONTH:02d}"
    largest_plan = max(plans, key=lambda p: p[enrollment_field])
    premium_archetype = archetypes_by_id[SCENARIO_PREMIUM_ARCHETYPE_ID]
    dental_archetype = archetypes_by_id[SCENARIO_DENTAL_ARCHETYPE_ID]

    cases.append(
        _build_case(
            case_id="scenario__premium_minus15_largest_plan",
            kind="scenario",
            description=(
                f"{SCENARIO_PREMIUM_ARCHETYPE_ID} against the full {settings.YEAR2} plan list, "
                f"with {largest_plan['plan_key']} ({largest_plan['org_name']}, the largest plan "
                f"by {enrollment_field}) discounted by $15/month premium."
            ),
            archetype=premium_archetype,
            plans=plans,
            base_coefficients=base_coefficients,
            plan_patches={largest_plan["plan_key"]: {"premium_total": largest_plan["premium_total"] + PREMIUM_DELTA}},
            plan_subset=None,
        )
    )
    cases.append(
        _build_case(
            case_id="scenario__dental_false_largest_plan",
            kind="scenario",
            description=(
                f"{SCENARIO_DENTAL_ARCHETYPE_ID} against the full {settings.YEAR2} plan list, "
                f"with {largest_plan['plan_key']} ({largest_plan['org_name']}, the largest plan "
                f"by {enrollment_field}) losing its comprehensive dental benefit."
            ),
            archetype=dental_archetype,
            plans=plans,
            base_coefficients=base_coefficients,
            plan_patches={largest_plan["plan_key"]: {"has_comprehensive_dental": False}},
            plan_subset=None,
        )
    )

    metadata = {
        "description": (
            "Python <-> TypeScript golden parity fixture for the Phase 3 "
            "multinomial-logit choice model (choice_model.choice_sets + "
            "choice_model.utility, ported 1:1 to app/src/lib/choice-model/). "
            "12 real archetypes (all 5 attitude segments, dual_proxy True/"
            "False, age_band 85+ included) evaluated against the full "
            f"{settings.YEAR2} plan list, plus 3 synthetic edge-case "
            "archetypes and 2 plan-attribute scenario variants. Real "
            "archetypes' prior_plan_year1 is keyed to Year-1 "
            f"({settings.YEAR1}) plan_keys but evaluated here against the "
            f"{settings.YEAR2} plan universe, so choice_sets."
            "renormalize_prior_plan legitimately drops prior mass on any "
            f"{settings.YEAR1}-only plan_key -- this is intentional, not a bug."
        ),
        "outside_option_key": OUTSIDE_KEY,
        "sources": {
            "coefficients": "data/processed/coefficients.json#base_coefficients",
            "archetypes": "data/processed/archetypes.json",
            "plans": f"data/processed/plans_{settings.YEAR2}.json",
        },
        "generator": "pipeline/export/golden_fixture.py",
        "comparison_tolerance": {
            "python_self_check_abs_tolerance": 1e-12,
            "typescript_relative_tolerance": 1e-9,
            "typescript_absolute_floor": 1e-12,
        },
        "case_derivation": (
            "Each case's actual plan list = plan_patches applied to the "
            "top-level `plans` array (shallow per-field override, keyed by "
            "plan_key), then restricted to `plan_subset` if it is not null."
        ),
        "n_cases": len(cases),
        "n_plans": len(plans),
    }

    return _json_safe(
        {
            "metadata": metadata,
            "base_coefficients": base_coefficients,
            "plans": plans,
            "cases": cases,
        }
    )


def write_fixture(output_path: Path | None = None) -> dict:
    result = build_fixture()
    dest = output_path if output_path is not None else settings.SHARED_GOLDEN_DIR / "parity_fixture.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    out = write_fixture()
    kinds = {}
    for case in out["cases"]:
        kinds[case["kind"]] = kinds.get(case["kind"], 0) + 1
    print(f"parity_fixture.json: {len(out['cases'])} cases ({kinds}), {len(out['plans'])} plans")
