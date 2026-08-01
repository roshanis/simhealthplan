"""Multinomial-logit utility and softmax choice-probability functions.

PURE module: no I/O, no globals besides plain-data constants, no
numpy/pandas -- everything is plain floats/dicts/lists. This is deliberate:
the module is ported 1:1 to TypeScript in a later phase (for the Next.js
app's in-browser choice model), so keep every function simple and explicit
rather than "clever"/vectorized. It's fast enough as-is for 80 archetypes x
~94 plans (see choice_model/calibrate.py, which calls this in a loop inside
an optimizer).

Utility spec (see coefficients.json for the fitted/documented values):

    U(archetype, plan) =
        b_premium * (premium_total / 10)
      + b_moop * (moop_inn / 1000)
      + b_dental * has_comprehensive_dental
      + b_vision_hearing * (has_vision + has_hearing_aids) / 2
      + b_otc * has_otc_or_flex
      + b_star * (star_rating - 3.5)
      + b_ppo * is_ppo
      + b_inertia * prior_prob(archetype, plan)

    U(archetype, outside) = b_outside + b_inertia * prior_prob(archetype, outside)

Archetype-level coefficients = base coefficients * SEGMENT_MULTIPLIERS[segment]
(missing entries default to 1.0; the "mixed" catch-all segment and any
unrecognized segment name are the identity -- all multipliers 1.0).

Probabilities are a softmax over whatever `plans` list is passed in. This
module has NO knowledge of D-SNP/I-SNP/C-SNP eligibility rules -- callers
(see choice_model/choice_sets.py) must pre-filter `plans` to the
archetype's ELIGIBLE choice set before calling `choice_probabilities`.
"""

from __future__ import annotations

import math

# Fixed, documented segment multipliers (Phase 3 spec). Any coefficient not
# listed for a segment implicitly multiplies by 1.0 (segment_coefficients
# fills gaps with 1.0). "mixed" -- the Phase 2 catch-all archetype segment
# -- and any other unrecognized segment name both resolve to the identity
# (no entry needed here for that; segment_coefficients handles it).
SEGMENT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "price_sensitive": {"b_premium": 1.6, "b_inertia": 0.6},
    "benefit_maximizer": {"b_dental": 1.5, "b_vision_hearing": 1.5, "b_otc": 1.5},
    "brand_loyal": {"b_inertia": 2.0},
    "health_status_driven": {"b_star": 1.5, "b_moop": 1.3},
    "mixed": {},
}

BASE_COEFFICIENT_NAMES: list[str] = [
    "b_premium",
    "b_moop",
    "b_dental",
    "b_vision_hearing",
    "b_otc",
    "b_star",
    "b_ppo",
    "b_inertia",
    "b_outside",
]

STAR_RATING_CENTER = 3.5
PREMIUM_DIVISOR = 10.0
MOOP_DIVISOR = 1000.0


def segment_coefficients(base_coefficients: dict[str, float], segment: str) -> dict[str, float]:
    """Archetype-level coefficients: base * SEGMENT_MULTIPLIERS[segment] (default 1.0)."""
    multipliers = SEGMENT_MULTIPLIERS.get(segment, {})
    return {name: value * multipliers.get(name, 1.0) for name, value in base_coefficients.items()}


def plan_utility(coefficients: dict[str, float], plan: dict, prior_prob: float) -> float:
    """U(archetype, plan) for one already-scaled coefficient dict."""
    star = plan.get("star_rating")
    if star is None:
        star = STAR_RATING_CENTER  # neutral; plan_attributes.py should already impute this.
    is_ppo = 1.0 if plan.get("is_ppo") else 0.0
    has_dental = 1.0 if plan.get("has_comprehensive_dental") else 0.0
    has_vision = 1.0 if plan.get("has_vision") else 0.0
    has_hearing = 1.0 if plan.get("has_hearing_aids") else 0.0
    has_otc = 1.0 if plan.get("has_otc_or_flex") else 0.0

    return (
        coefficients["b_premium"] * (plan["premium_total"] / PREMIUM_DIVISOR)
        + coefficients["b_moop"] * (plan["moop_inn"] / MOOP_DIVISOR)
        + coefficients["b_dental"] * has_dental
        + coefficients["b_vision_hearing"] * ((has_vision + has_hearing) / 2.0)
        + coefficients["b_otc"] * has_otc
        + coefficients["b_star"] * (star - STAR_RATING_CENTER)
        + coefficients["b_ppo"] * is_ppo
        + coefficients["b_inertia"] * prior_prob
    )


def outside_utility(coefficients: dict[str, float], prior_prob_outside: float) -> float:
    """U(archetype, outside) for one already-scaled coefficient dict."""
    return coefficients["b_outside"] + coefficients["b_inertia"] * prior_prob_outside


def choice_probabilities(
    base_coefficients: dict[str, float],
    segment: str,
    plans: list[dict],
    prior_plan: dict[str, float],
    outside_key: str,
) -> dict[str, float]:
    """Softmax choice probabilities over `plans` (already eligibility-filtered) + outside.

    `prior_plan` maps plan_key/outside_key -> Year-1 prior probability (the
    inertia term); a missing key defaults to 0.0. Returns a dict
    plan_key/outside_key -> probability, summing to 1.0.
    """
    coefficients = segment_coefficients(base_coefficients, segment)

    keys: list[str] = []
    utilities: list[float] = []
    for plan in plans:
        key = plan["plan_key"]
        keys.append(key)
        utilities.append(plan_utility(coefficients, plan, prior_plan.get(key, 0.0)))
    keys.append(outside_key)
    utilities.append(outside_utility(coefficients, prior_plan.get(outside_key, 0.0)))

    max_u = max(utilities)
    exps = [math.exp(u - max_u) for u in utilities]
    total = sum(exps)
    return {key: value / total for key, value in zip(keys, exps)}
