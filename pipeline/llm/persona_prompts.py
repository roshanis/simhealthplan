"""Phase 4 LLM persona prompts: consideration-set construction + the two
structured-output prompt builders (CHOICE, BACKSTORY) consumed by
``llm/run_persona_pass.py``.

Both prompt builders return a plain dict shaped exactly for
``llm.client.LLMClient.complete_structured(prompt_key, system, user,
response_schema, schema_version)`` -- callers just splat/pull those keys,
they never need to know the prompt text layout.

Design notes
------------
* **Consideration set is eligibility-first.** ``build_consideration_set``
  only ever draws from the caller-supplied ``eligible_plan_keys`` -- the
  archetype's already D-SNP/I-SNP/C-SNP-filtered 2025 eligible set from
  ``choice_model.choice_sets`` / ``choice_model.predict``. This is what
  guarantees a non-dual archetype's consideration set can never contain a
  D-SNP plan, independent of whatever the logit probs or crosswalked prior
  happen to contain for that key.
* **Current coverage (2024) vs. consideration set (2025) use different plan
  spaces on purpose.** The "current coverage" summary shown to the persona
  describes their actual 2024 plan (what they are switching *from*), using
  ``plans_2024.json`` names. The consideration set is 2025 plans only (what
  they are choosing *for* 2025); "the plan holding this archetype's largest
  prior mass" specifically means the archetype's crosswalk-mapped 2025
  *renormalized* prior (``choice_model.predict.predict_for_archetype``'s
  ``renormalized_prior``), i.e. wherever their 2024 plan's mass landed after
  crossing the disposition (renewed/renumbered/consolidated/terminated) --
  not the raw 2024 plan_key, which usually isn't even a valid 2025 plan_key.
* **The outside option is listed but never counted in K.** Per spec, K=8
  covers plan alternatives only; the "no 2025 MA plan" outside option is
  always additionally listed (`format_alternatives_block` appends it), and
  the response schema's ranking always includes it as one more key to rank.
* **Strict-schema-safe.** The CHOICE response schema constrains
  ``ranked_plan_keys`` items to an ``enum`` of exactly this request's
  alternative keys (plan-agnostic, no OpenAI-strict-mode ambiguity), but
  deliberately does *not* set ``minItems``/``maxItems`` (not confirmed part
  of the documented strict-mode JSON Schema subset) -- the system prompt
  instructs a full ranking instead, and callers (``run_persona_pass``)
  defensively sanitize whatever comes back into a valid permutation of the
  alternative keys regardless.
"""

from __future__ import annotations

CHOICE_PROMPT_KEY = "y2_choice_v1"
CHOICE_SCHEMA_VERSION = "v1"
BACKSTORY_PROMPT_KEY = "backstory_v1"
BACKSTORY_SCHEMA_VERSION = "v1"

DEFAULT_CONSIDERATION_SET_SIZE = 8
TOP_ENROLLMENT_PLAN_COUNT = 2
TOP_PRIOR_MASS_PLAN_COUNT = 1
ENROLLMENT_FIELD_2025 = "enrollment_2025_03"
DEFAULT_COVERAGE_SUMMARY_TOP_N = 3

# Demographic-realism labels for the backstory prompt only (see build_traits
# in archetypes/traits.py for why race_eth is excluded from *attitude*
# trait-phrase generation but is fine to surface here as plain demographic
# context -- see that module's docstring). "mixed" is Phase 2's aggregated
# catch-all archetype value, not a demographic category.
_RACE_ETH_LABELS: dict[str, str] = {
    "asian_nh": "Asian, non-Hispanic",
    "black_nh": "Black, non-Hispanic",
    "hispanic": "Hispanic or Latino",
    "other_multi_nh": "another race or multiple races, non-Hispanic",
    "white_nh": "White, non-Hispanic",
    "mixed": "a mixed/aggregated demographic group (this archetype is a catch-all, not one specific background)",
}


# --- small formatting helpers ---------------------------------------------------


def _yn(flag: object) -> str:
    return "yes" if bool(flag) else "no"


def format_archetype_profile(archetype: dict) -> str:
    """Human-readable one-line profile from committed, evidence-based fields
    only (age_band/income_tier/dual_proxy/attitude_segment/traits -- the
    same fields ``archetypes/traits.py`` draws on)."""
    traits = "; ".join(archetype.get("traits", [])) or "no distinguishing traits on file"
    dual_note = "Likely dual-eligible (Medicare + Medicaid)." if archetype.get("dual_proxy") else "Not dual-eligible."
    return (
        f"Age band: {archetype.get('age_band')}. Income tier: {archetype.get('income_tier')}. "
        f"{dual_note} Attitude segment: {archetype.get('attitude_segment')}. Traits: {traits}."
    )


def format_current_coverage_summary(
    prior_plan_year1: dict[str, float],
    plans_2024_by_key: dict[str, dict],
    outside_key_year1: str,
    top_n: int = DEFAULT_COVERAGE_SUMMARY_TOP_N,
) -> str:
    """Top-``top_n`` 2024 prior plans by mass, always also stating the
    outside-option share explicitly (even when it doesn't rank in the top
    N) per spec ("incl. outside option share")."""
    ranked = sorted(
        ((key, prob) for key, prob in prior_plan_year1.items() if prob > 0),
        key=lambda item: (-item[1], item[0]),
    )
    lines = []
    for key, prob in ranked[:top_n]:
        if key == outside_key_year1:
            label = "no MA plan in 2024 (traditional Medicare or an unmodeled legacy plan)"
        else:
            plan = plans_2024_by_key.get(key)
            label = plan["plan_name"] if plan else key
        lines.append(f"{prob * 100:.1f}% {label}")

    outside_share = prior_plan_year1.get(outside_key_year1, 0.0)
    summary = "; ".join(lines) if lines else "no significant prior coverage on file"
    return f"Most likely 2024 coverage for beneficiaries like this persona: {summary}. (Outside/no-MA-plan share: {outside_share * 100:.1f}%.)"


def format_plan_line(plan: dict) -> str:
    return (
        f"{plan['plan_key']} -- {plan['plan_name']} ({plan['plan_type']}): "
        f"${plan['premium_total']:.2f}/mo premium, ${plan['moop_inn']:,.0f} MOOP, "
        f"star {plan['star_rating']:.1f}, Dental: {_yn(plan.get('has_comprehensive_dental'))}, "
        f"Vision: {_yn(plan.get('has_vision'))}, Hearing aids: {_yn(plan.get('has_hearing_aids'))}, "
        f"OTC/flex: {_yn(plan.get('has_otc_or_flex'))}"
    )


def format_alternatives_block(consideration_plan_keys: list[str], plans_2025_by_key: dict[str, dict], outside_key: str) -> str:
    lines = [f"{i}. {format_plan_line(plans_2025_by_key[key])}" for i, key in enumerate(consideration_plan_keys, start=1)]
    lines.append(
        f"{len(consideration_plan_keys) + 1}. {outside_key} -- No 2025 Medicare Advantage plan "
        "(traditional Medicare, or coverage outside this county's modeled 2025 MA lineup)"
    )
    return "\n".join(lines)


# --- consideration set --------------------------------------------------------


def _enrollment_lookup(plans_2025: list[dict]) -> dict[str, float]:
    return {plan["plan_key"]: float(plan.get(ENROLLMENT_FIELD_2025, 0.0)) for plan in plans_2025}


def build_consideration_set(
    eligible_plan_keys: list[str],
    logit_probs: dict[str, float],
    renormalized_prior: dict[str, float],
    plans_2025: list[dict],
    outside_key: str,
    k: int = DEFAULT_CONSIDERATION_SET_SIZE,
) -> list[str]:
    """Top-K (default 8) 2025 plan_keys for this archetype's LLM consideration
    set. Never includes the outside option (callers list it separately).

    Restricted throughout to `eligible_plan_keys` so an ineligible plan --
    e.g. a D-SNP plan for a non-dual archetype -- can never appear here,
    regardless of what `logit_probs`/`renormalized_prior` contain for that
    key.

    Composition, in priority order (deduped, capped to `k`, ties broken
    deterministically by plan_key):
      1. the single eligible plan holding this archetype's largest
         crosswalk-mapped prior mass (its "current plan going into 2025"),
         if any eligible plan has nonzero prior mass;
      2. the `TOP_ENROLLMENT_PLAN_COUNT` (2) largest-2025-enrollment
         eligible plans (market-context anchors);
      3. remaining eligible plans ranked by this archetype's own logit
         choice probability, filling any leftover slots up to `k`.
    """
    eligible_set = {key for key in eligible_plan_keys if key != outside_key}
    enrollment = _enrollment_lookup(plans_2025)

    ranked_by_prior = sorted(
        (key for key in eligible_set if renormalized_prior.get(key, 0.0) > 0),
        key=lambda key: (-renormalized_prior.get(key, 0.0), key),
    )
    ranked_by_enrollment = sorted(eligible_set, key=lambda key: (-enrollment.get(key, 0.0), key))
    ranked_by_logit = sorted(eligible_set, key=lambda key: (-logit_probs.get(key, 0.0), key))

    seeds = [*ranked_by_prior[:TOP_PRIOR_MASS_PLAN_COUNT], *ranked_by_enrollment[:TOP_ENROLLMENT_PLAN_COUNT], *ranked_by_logit]

    ordered: list[str] = []
    seen: set[str] = set()
    for key in seeds:
        if key in seen:
            continue
        if len(ordered) >= k:
            break
        ordered.append(key)
        seen.add(key)
    return ordered


# --- CHOICE prompt -------------------------------------------------------------


def choice_response_schema(alternative_keys: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "ranked_plan_keys": {
                "type": "array",
                "items": {"type": "string", "enum": list(alternative_keys)},
            },
            "switching_propensity": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
        },
        "required": ["ranked_plan_keys", "switching_propensity", "rationale"],
        "additionalProperties": False,
    }


def build_choice_prompt(
    archetype: dict,
    plans_2024_by_key: dict[str, dict],
    plans_2025_by_key: dict[str, dict],
    consideration_plan_keys: list[str],
    outside_key_year1: str,
    outside_key_year2: str,
) -> dict:
    """Everything needed for one CHOICE ``LLMClient.complete_structured`` call.

    Returns ``{"prompt_key", "schema_version", "system", "user",
    "response_schema", "alternative_keys"}`` -- ``alternative_keys`` (the
    consideration set + the outside key, in listed order) is also handed
    back so callers/tests know exactly what a valid ``ranked_plan_keys``
    permutation looks like without re-deriving it.
    """
    alternative_keys = [*consideration_plan_keys, outside_key_year2]
    profile = format_archetype_profile(archetype)
    coverage_summary = format_current_coverage_summary(archetype.get("prior_plan_year1", {}), plans_2024_by_key, outside_key_year1)
    alternatives_block = format_alternatives_block(consideration_plan_keys, plans_2025_by_key, outside_key_year2)

    system = (
        "You are role-playing a single fictional Medicare Advantage beneficiary persona in "
        "Maricopa County, Arizona, choosing among 2025 Medicare Advantage plan options. Answer "
        "strictly in character, from this persona's own point of view, using only the profile "
        "and plan information given below. Respond with a single JSON object matching the "
        "required schema -- no prose outside the JSON.\n\n"
        "You must rank every single listed alternative (including the 'no 2025 MA plan' outside "
        "option) from most to least preferred, using each alternative's exact key exactly once "
        "in ranked_plan_keys. switching_propensity is this persona's own 0 (definitely stay in "
        "whatever 2025 plan continues their prior coverage) to 1 (definitely and actively switch "
        "away from it) estimate of how likely they are to leave their prior plan. rationale is "
        "1-2 sentences, written in the first person, explaining the ranking."
    )
    user = (
        f"Archetype ID: {archetype['id']}\n"
        f"Persona profile: {profile}\n\n"
        f"{coverage_summary}\n\n"
        "2025 plan alternatives to rank (plan_key -- plan name (type): attributes):\n"
        f"{alternatives_block}"
    )
    return {
        "prompt_key": CHOICE_PROMPT_KEY,
        "schema_version": CHOICE_SCHEMA_VERSION,
        "system": system,
        "user": user,
        "response_schema": choice_response_schema(alternative_keys),
        "alternative_keys": alternative_keys,
    }


# --- BACKSTORY prompt -----------------------------------------------------------


def backstory_response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "backstory": {"type": "string"},
        },
        "required": ["name", "backstory"],
        "additionalProperties": False,
    }


def build_backstory_prompt(archetype: dict) -> dict:
    """Everything needed for one BACKSTORY ``LLMClient.complete_structured`` call."""
    traits = "; ".join(archetype.get("traits", [])) or "no distinguishing traits on file"
    race_label = _RACE_ETH_LABELS.get(archetype.get("race_eth", ""), str(archetype.get("race_eth", "unspecified")))

    system = (
        "You invent a single clearly fictional Medicare beneficiary persona for an internal "
        "simulation demo -- not a real person, living or dead. Respond with a single JSON "
        "object matching the required schema -- no prose outside the JSON.\n\n"
        "Give the persona a first and last name that reflects the plausible, genuine name "
        "diversity found within any real demographic group, WITHOUT stereotyping: do not "
        "mechanically derive the name from the persona's race/ethnicity (e.g. do not always "
        "assign a name that 'matches' that group, and do not treat race/ethnicity as a lookup "
        "table for names). Choose a name the way real name diversity actually works -- varied, "
        "and not mechanically predictable from any single demographic field below.\n\n"
        "backstory is one short paragraph (3-5 sentences), third person, grounding the persona "
        "in their age, income situation, and listed traits -- how they think about their health "
        "coverage, their day-to-day life, and what matters to them in a Medicare Advantage plan. "
        "Do not name specific real companies, real plan names, or real places beyond a generic "
        "reference to living in Maricopa County, Arizona."
    )
    user = (
        f"Archetype ID: {archetype['id']}\n"
        f"Age band: {archetype.get('age_band')}\n"
        f"Income tier: {archetype.get('income_tier')}\n"
        f"Dual-eligible (Medicare + Medicaid) proxy: {bool(archetype.get('dual_proxy'))}\n"
        f"Race/ethnicity (demographic context only -- see system instructions on names): {race_label}\n"
        f"Attitude segment: {archetype.get('attitude_segment')}\n"
        f"Traits: {traits}"
    )
    return {
        "prompt_key": BACKSTORY_PROMPT_KEY,
        "schema_version": BACKSTORY_SCHEMA_VERSION,
        "system": system,
        "user": user,
        "response_schema": backstory_response_schema(),
    }
