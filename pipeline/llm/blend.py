"""Phase 4 logit/LLM blend: pure functions that fold one archetype's LLM
CHOICE output (a full ranking of its consideration set + outside option,
plus a switching_propensity) into the Phase 3 multinomial-logit utility
model, then re-softmax.

PURE module (mirrors ``choice_model/utility.py``'s "no I/O, no globals
besides plain-data constants" discipline) -- it reuses
``utility.segment_coefficients`` / ``utility.plan_utility`` /
``utility.outside_utility`` rather than recomputing the base utility model,
and only adds two archetype-level adjustments on top:

1. **Rank bonus** (``rank_bonus``): an LLM-ranked alternative at position
   ``rank`` (1-indexed) out of ``K`` ranked alternatives gets an additive
   utility bump ``ALPHA * (1 - (rank - 1) / (K - 1))`` -- ``ALPHA`` at rank 1,
   linearly down to 0 at the last-ranked alternative (``K == 1`` is a
   degenerate single-alternative "ranking", which trivially gets the full
   ``ALPHA`` bonus). This lets the LLM's holistic reasoning (things the
   9-coefficient linear utility model can't see, e.g. plan-name framing or
   how these specific plans compare and contrast for this specific persona's
   story) shift relative attractiveness within the consideration set,
   without ever dominating the calibrated economic coefficients: ALPHA=0.35
   is small relative to typical utility spreads in this fitted model (e.g.
   b_inertia ~37, so even a middling prior-mass difference outweighs the
   full rank bonus).
2. **Inertia modulation** (``inertia_multiplier``): the archetype's own
   ``switching_propensity`` (0=definitely stay, 1=definitely switch) scales
   the fitted ``b_inertia`` coefficient by a clamped multiplier in
   [0.85, 1.15] -- a low switching_propensity *strengthens* status-quo
   inertia (up to +15%), a high one *weakens* it (down to -15%), symmetric
   around switching_propensity=1/3 (`1.15 - 0.30*(1/3) = 1.05`... note the
   multiplier is 1.0 exactly at switching_propensity=0.5).

Both adjustments are applied to utilities, then the whole eligible set +
outside option is re-softmaxed exactly like ``utility.choice_probabilities``
does -- see ``blended_choice_probabilities``.
"""

from __future__ import annotations

import math

from choice_model import utility

ALPHA = 0.35

INERTIA_MULT_BASE = 1.15
INERTIA_MULT_SENSITIVITY = 0.30
INERTIA_MULT_MIN = 0.85
INERTIA_MULT_MAX = 1.15


def rank_bonus(ranked_keys: list[str], alpha: float = ALPHA) -> dict[str, float]:
    """delta_u per ranked key: ``alpha`` at rank 1, linear down to 0 at the
    last rank. Keys not present in ``ranked_keys`` simply aren't in the
    returned dict (callers should ``.get(key, 0.0)``). Empty input -> {}."""
    k = len(ranked_keys)
    if k == 0:
        return {}
    if k == 1:
        return {ranked_keys[0]: alpha}
    return {key: alpha * (1.0 - rank / (k - 1)) for rank, key in enumerate(ranked_keys)}


def inertia_multiplier(switching_propensity: float) -> float:
    """clamp(1.15 - 0.30 * switching_propensity, 0.85, 1.15)."""
    raw = INERTIA_MULT_BASE - INERTIA_MULT_SENSITIVITY * switching_propensity
    return max(INERTIA_MULT_MIN, min(INERTIA_MULT_MAX, raw))


def blended_choice_probabilities(
    base_coefficients: dict[str, float],
    segment: str,
    plans: list[dict],
    prior_plan: dict[str, float],
    outside_key: str,
    ranked_plan_keys: list[str],
    switching_propensity: float,
    alpha: float = ALPHA,
) -> dict[str, float]:
    """Softmax choice probabilities over `plans` (eligibility-filtered, same
    contract as ``utility.choice_probabilities``) + outside, after applying
    the LLM-derived rank bonus and inertia modulation.

    Signature deliberately mirrors ``utility.choice_probabilities`` (same
    first five positional args) plus the two LLM-derived inputs, so a
    blended call site looks like a drop-in variant of the pure-logit call.
    """
    coefficients = utility.segment_coefficients(base_coefficients, segment)
    multiplier = inertia_multiplier(switching_propensity)
    modulated_coefficients = {**coefficients, "b_inertia": coefficients["b_inertia"] * multiplier}
    bonus = rank_bonus(ranked_plan_keys, alpha)

    keys: list[str] = []
    utilities: list[float] = []
    for plan in plans:
        key = plan["plan_key"]
        keys.append(key)
        base_u = utility.plan_utility(modulated_coefficients, plan, prior_plan.get(key, 0.0))
        utilities.append(base_u + bonus.get(key, 0.0))
    keys.append(outside_key)
    outside_u = utility.outside_utility(modulated_coefficients, prior_plan.get(outside_key, 0.0))
    utilities.append(outside_u + bonus.get(outside_key, 0.0))

    max_u = max(utilities)
    exps = [math.exp(u - max_u) for u in utilities]
    total = sum(exps)
    return {key: value / total for key, value in zip(keys, exps)}


def l1_distance(probs_a: dict[str, float], probs_b: dict[str, float]) -> float:
    """sum(|a[k] - b[k]|) over the union of both dicts' keys -- a simple,
    dependency-free divergence measure for the blend-bounded property tests."""
    keys = set(probs_a) | set(probs_b)
    return sum(abs(probs_a.get(key, 0.0) - probs_b.get(key, 0.0)) for key in keys)
