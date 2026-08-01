"""Phase 5 Monte Carlo confidence bounds (p10/p50/p90) for the backtest's
predicted 2025 aggregate shares.

Two independent sources of Year-2 forecast uncertainty are jittered per
Monte Carlo draw, both parameters given directly by the Phase 5 spec:

  * **Coefficient jitter**: each of the 9 calibrated base coefficients ~
    Normal(b, max(0.10*|b|, 0.01)), clipped to the same documented economic
    sign bounds ``choice_model.calibrate``'s optimizer itself respects
    (``calibrate.BOUNDS`` -- reused, not re-derived).
  * **Archetype weight jitter**: each archetype's population weight is
    perturbed log-normally (sd 0.10 in log-space: ``w_i' = w_i *
    exp(Normal(0, 0.10))``), then rescaled so the total population is
    unchanged.

Every draw recomputes the full-population aggregate 2025 share via the same
pure ``choice_model.utility.choice_probabilities`` /
``choice_model.predict.aggregate_weighted_shares`` (logit) or
``llm.blend.blended_choice_probabilities`` (blended) functions the point
estimate itself uses -- no choice-probability math is reimplemented here,
only the jitter + percentile-summary layer around it. For the blended
variant, the LLM-derived rank bonus / inertia multiplier are held FIXED
across draws (an archetype's ``ranked_plan_keys``/``switching_propensity``
are never jittered, per spec) -- only the coefficients and archetype
weights vary; ``blend.blended_choice_probabilities`` recomputes the same
fixed rank-bonus/inertia-multiplier from those fixed inputs every draw, it's
just re-combined with that draw's jittered coefficients.

Eligibility filtering and the crosswalked/renormalized Year-2 prior are
coefficient-independent, so they're computed ONCE per archetype up front
(``_prepare_archetypes``) rather than inside the draw loop -- a performance
optimization (this is what keeps N=1000 draws under the spec's 60s budget),
not a change in what's computed: it's exactly the same two steps
``choice_model.predict.predict_for_archetype`` runs internally, just
factored out of the per-draw hot path since they don't depend on the
per-draw jittered coefficients.
"""

from __future__ import annotations

import numpy as np

from choice_model import choice_sets, predict, utility
from choice_model.calibrate import BOUNDS as COEFFICIENT_BOUNDS
from config.settings import settings
from llm import blend

N_DRAWS_DEFAULT = 1000
WEIGHT_JITTER_SD = 0.10
COEFFICIENT_JITTER_MIN_SD = 0.01
COEFFICIENT_JITTER_RELATIVE_SD = 0.10

PERCENTILES: tuple[int, ...] = (10, 50, 90)


# --- jitter -----------------------------------------------------------------------------


def jitter_coefficients(
    base_coefficients: dict[str, float],
    rng: np.random.Generator,
    bounds: dict[str, tuple[float, float]] | None = None,
) -> dict[str, float]:
    """One Monte Carlo draw of the 9 base coefficients: each ~ Normal(b,
    max(0.10*|b|, 0.01)), clipped to ``bounds[name]`` (defaults to
    ``choice_model.calibrate.BOUNDS``, the same sign bounds the calibration
    optimizer itself respects). Draws in ``utility.BASE_COEFFICIENT_NAMES``
    fixed order so the rng stream is reproducible regardless of dict
    insertion order.
    """
    effective_bounds = bounds if bounds is not None else COEFFICIENT_BOUNDS
    jittered: dict[str, float] = {}
    for name in utility.BASE_COEFFICIENT_NAMES:
        value = base_coefficients[name]
        sd = max(COEFFICIENT_JITTER_RELATIVE_SD * abs(value), COEFFICIENT_JITTER_MIN_SD)
        draw = rng.normal(value, sd)
        lo, hi = effective_bounds.get(name, (-np.inf, np.inf))
        jittered[name] = float(np.clip(draw, lo, hi))
    return jittered


def jitter_weights(archetypes: list[dict], rng: np.random.Generator, sd: float = WEIGHT_JITTER_SD) -> dict[str, float]:
    """One Monte Carlo draw of archetype population weights: log-normal
    multiplicative jitter (sd in log-space), rescaled so the total
    population (sum of weights) exactly matches the input."""
    ids = [archetype["id"] for archetype in archetypes]
    weights = np.array([float(archetype["weight"]) for archetype in archetypes], dtype=float)
    total = weights.sum()

    log_jitter = rng.normal(0.0, sd, size=len(weights))
    jittered = weights * np.exp(log_jitter)
    jittered_total = jittered.sum()
    if jittered_total > 0:
        jittered = jittered * (total / jittered_total)
    return dict(zip(ids, jittered))


# --- prep (coefficient-independent, computed once) --------------------------------------


def _prepare_archetypes(
    archetypes: list[dict],
    plans_2025: list[dict],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str,
    outside_key_year2: str,
) -> list[dict]:
    """Per-archetype eligible-plan list + renormalized Year-2 prior -- the
    coefficient-independent half of ``predict.predict_for_archetype``,
    computed once rather than on every Monte Carlo draw."""
    prepared = []
    for archetype in archetypes:
        year2_prior_raw = predict.map_prior_year1_to_year2(
            archetype.get("prior_plan_year1", {}), crosswalk_map, outside_key_year1, outside_key_year2
        )
        eligible = choice_sets.eligible_plans(archetype, plans_2025)
        renormalized_prior = choice_sets.renormalize_prior_plan(year2_prior_raw, archetype, plans_2025, outside_key_year2)
        prepared.append(
            {
                "id": archetype["id"],
                "segment": archetype["attitude_segment"],
                "eligible_plans": eligible,
                "renormalized_prior": renormalized_prior,
            }
        )
    return prepared


# --- percentile summary -----------------------------------------------------------------


def percentile_bounds(
    draws: list[dict[str, float]], percentiles: tuple[int, ...] = PERCENTILES
) -> dict[str, dict[str, float]]:
    """Per-key p10/p50/p90 (or whichever ``percentiles``) across a list of
    per-draw aggregate-share dicts. A key missing from a given draw defaults
    to 0.0 for that draw (shouldn't happen in practice here -- every draw
    shares the same eligibility-derived key set -- but keeps this function
    correct as a standalone utility)."""
    if not draws:
        return {}
    keys: set[str] = set()
    for draw in draws:
        keys.update(draw.keys())

    result: dict[str, dict[str, float]] = {}
    for key in keys:
        values = np.array([draw.get(key, 0.0) for draw in draws], dtype=float)
        result[key] = {f"p{p}": float(np.percentile(values, p)) for p in percentiles}
    return result


# --- orchestration -----------------------------------------------------------------------


def run_bounds(
    archetypes: list[dict],
    plans_2025: list[dict],
    base_coefficients: dict[str, float],
    crosswalk_map: dict[str, dict],
    n_draws: int = N_DRAWS_DEFAULT,
    seed: int = settings.SEED,
    coefficient_bounds: dict[str, tuple[float, float]] | None = None,
    weight_jitter_sd: float = WEIGHT_JITTER_SD,
    outside_key_year1: str = predict.OUTSIDE_KEY_YEAR1,
    outside_key_year2: str = predict.OUTSIDE_KEY_YEAR2,
    blend_inputs: dict[str, dict] | None = None,
) -> dict[str, dict[str, float]]:
    """``n_draws`` Monte Carlo draws of the aggregate 2025 share, jittering
    coefficients + archetype weights each draw; returns per-key p10/p50/p90.

    ``blend_inputs`` (optional): ``{archetype_id: {"ranked_plan_keys":
    [...], "switching_propensity": float}}`` -- when given, each draw uses
    ``llm.blend.blended_choice_probabilities`` with these held FIXED (per
    spec, only the coefficients/weights vary draw to draw); when omitted,
    each draw uses the pure logit ``choice_model.utility.choice_probabilities``.
    Deterministic given a fixed ``seed`` (uses ``numpy.random.default_rng``).
    """
    prepared = _prepare_archetypes(archetypes, plans_2025, crosswalk_map, outside_key_year1, outside_key_year2)
    rng = np.random.default_rng(seed)

    draws: list[dict[str, float]] = []
    for _ in range(n_draws):
        coefficients = jitter_coefficients(base_coefficients, rng, coefficient_bounds)
        weights = jitter_weights(archetypes, rng, weight_jitter_sd)

        probs_by_archetype: dict[str, dict[str, float]] = {}
        for entry in prepared:
            aid = entry["id"]
            if blend_inputs is not None:
                persona = blend_inputs[aid]
                probs_by_archetype[aid] = blend.blended_choice_probabilities(
                    coefficients,
                    entry["segment"],
                    entry["eligible_plans"],
                    entry["renormalized_prior"],
                    outside_key_year2,
                    persona["ranked_plan_keys"],
                    persona["switching_propensity"],
                )
            else:
                probs_by_archetype[aid] = utility.choice_probabilities(
                    coefficients, entry["segment"], entry["eligible_plans"], entry["renormalized_prior"], outside_key_year2
                )

        archetypes_this_draw = [{"id": entry["id"], "weight": weights[entry["id"]]} for entry in prepared]
        draws.append(predict.aggregate_weighted_shares(archetypes_this_draw, probs_by_archetype))

    return percentile_bounds(draws)
