"""Phase 3 Year-1 calibration: fits the 9 base multinomial-logit coefficients.

Loads ``data/processed/archetypes.json`` (Phase 2, 80 archetypes) and
``data/processed/plans_2024.json`` (this phase's ``plan_attributes.py``, 93
plans), applies the ``choice_sets`` eligibility rules (zeroing/renormalizing
each archetype's prior over its eligible choice set), and fits the 9 base
coefficients in ``utility.BASE_COEFFICIENT_NAMES`` by minimizing size-
weighted squared error between predicted aggregate Year-1 shares (summed
over archetypes: weight * choice probability) and actual 2024 shares (93
plans' CPSC enrollment + an outside share = eligibles minus modeled-plan
enrollment), via ``scipy.optimize.minimize`` (L-BFGS-B), with:

  * sign bounds matching economic priors (b_premium/b_moop <= 0;
    b_dental/b_vision_hearing/b_otc/b_star/b_inertia >= 0; b_ppo/b_outside
    unconstrained -- see BOUNDS),
  * a small L2 pull toward documented economic-prior starting values
    (each start is pulled toward its own anchor -- PRIOR_COEFFICIENTS or
    STRONG_INERTIA_PRIOR_COEFFICIENTS, weighted by L2_LAMBDA -- to
    discourage the optimizer from drifting to an implausible-magnitude
    local optimum while it explores each anchor's basin),
  * 3 seeded multi-starts (``numpy.random.default_rng(settings.SEED)``) to
    reduce the chance of reporting a bad local optimum; the lowest-loss
    start's result is kept. See STRONG_INERTIA_PRIOR_COEFFICIENTS's
    docstring for why two distinct anchor priors (not just noise around
    one) are used: this market's loss surface is genuinely multi-modal.

Writes ``data/processed/coefficients.json``: the complete, flat,
language-neutral evaluation spec (base coefficients, segment multipliers,
attribute scaling rules, choice-set rules, calibration + Year-1 fit
metadata) that a later-phase TypeScript port of ``utility.py`` +
``choice_sets.py`` needs to reproduce this model exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from archetypes.plan_priors import OUTSIDE_PLAN_KEY
from choice_model import choice_sets, utility
from choice_model.schemas import CoefficientsFile
from config.settings import settings

# --- Economic priors & bounds ---------------------------------------------------
# Documented starting guesses for the L2 pull term: mild, sane-sign
# magnitudes in the model's native scaling (utility units per $10 premium,
# per $1000 MOOP, per benefit flag, per star point above/below 3.5, per PPO
# flag, per unit of Year-1 prior probability). Not fitted -- these anchor
# the optimizer away from implausible local optima, they are not claimed to
# be the "right" answer on their own.
PRIOR_COEFFICIENTS: dict[str, float] = {
    "b_premium": -0.5,
    "b_moop": -0.3,
    "b_dental": 0.5,
    "b_vision_hearing": 0.5,
    "b_otc": 0.5,
    "b_star": 0.5,
    "b_ppo": 0.0,
    # Medicare Advantage enrollees are famously "sticky" -- annual switching
    # rates in the real market are in the single digits -- so a prior on
    # status-quo/inertia utility is itself economically well-grounded, not
    # just a numerical convenience.
    "b_inertia": 15.0,
    "b_outside": -1.00,
}

# A second, "strong-inertia" documented economic prior used to seed the
# third multi-start (see START below). Some plans in this market (e.g. the
# dominant D-SNP option among dual-eligible archetypes' much smaller
# eligible choice set) hold a very concentrated share of their eligible
# population's Year-1 prior mass -- reproducing that through a softmax that
# is *linear* in prior probability (per the utility spec) requires a
# materially larger inertia coefficient than the flatter, ~90-plan non-SNP
# market needs on its own. Exploring that distinct, empirically-motivated
# regime as an explicit alternate start (rather than only jittering around
# the moderate PRIOR_COEFFICIENTS) is what lets the multi-start reliably
# avoid the shallower, worse-fitting local optima the moderate prior alone
# tends to converge to.
STRONG_INERTIA_PRIOR_COEFFICIENTS: dict[str, float] = {
    "b_premium": -1.0,
    "b_moop": -0.3,
    "b_dental": 2.0,
    "b_vision_hearing": 1.5,
    "b_otc": 2.0,
    "b_star": 1.0,
    "b_ppo": 0.0,
    "b_inertia": 35.0,
    "b_outside": -5.0,
}

BOUNDS: dict[str, tuple[float, float]] = {
    "b_premium": (-10.0, 0.0),
    "b_moop": (-10.0, 0.0),
    "b_dental": (0.0, 10.0),
    "b_vision_hearing": (0.0, 10.0),
    "b_otc": (0.0, 10.0),
    "b_star": (0.0, 10.0),
    "b_ppo": (-10.0, 10.0),
    "b_inertia": (0.0, 80.0),
    "b_outside": (-20.0, 20.0),
}

L2_LAMBDA = 1e-6
N_STARTS = 3
# Anchor coefficient dict for each of the N_STARTS multi-starts (cycled if
# N_STARTS > len(START_ANCHORS)). Start 0 uses PRIOR_COEFFICIENTS
# unperturbed; every other start is a small seeded perturbation (see
# START_PERTURBATION_SCALES) of its anchor -- this is what "3 seeded
# starts" means here: deterministic given settings.SEED, but exploring two
# genuinely distinct, documented economic-prior regions rather than just
# jittering once around a single guess.
START_ANCHORS: list[dict[str, float]] = [PRIOR_COEFFICIENTS, PRIOR_COEFFICIENTS, STRONG_INERTIA_PRIOR_COEFFICIENTS]
START_PERTURBATION_SCALES = [0.0, 0.15, 0.15]  # fraction of each coefficient's bound half-width
MAX_ITER = 2000


# --- vector <-> dict helpers ------------------------------------------------------


def coefficients_to_vector(coefficients: dict[str, float]) -> np.ndarray:
    return np.array([coefficients[name] for name in utility.BASE_COEFFICIENT_NAMES], dtype=float)


def vector_to_coefficients(x: np.ndarray) -> dict[str, float]:
    return {name: float(value) for name, value in zip(utility.BASE_COEFFICIENT_NAMES, x)}


def bounds_vector() -> list[tuple[float, float]]:
    return [BOUNDS[name] for name in utility.BASE_COEFFICIENT_NAMES]


# --- data prep ----------------------------------------------------------------------


def prepare_archetype_choice_data(
    archetypes: list[dict],
    plans: list[dict],
    outside_key: str = OUTSIDE_PLAN_KEY,
) -> list[dict]:
    """Precompute each archetype's eligible-plan choice set + renormalized prior once.

    Doing this outside the optimizer's objective function avoids redoing
    the (coefficient-independent) eligibility filtering / renormalization
    on every one of the optimizer's few-thousand objective evaluations.
    """
    prepared = []
    for archetype in archetypes:
        eligible = choice_sets.eligible_plans(archetype, plans)
        renormalized_prior = choice_sets.renormalize_prior_plan(
            archetype.get("prior_plan_year1", {}), archetype, plans, outside_key
        )
        prepared.append(
            {
                "id": archetype["id"],
                "weight": float(archetype["weight"]),
                "segment": archetype["attitude_segment"],
                "eligible_plans": eligible,
                "renormalized_prior": renormalized_prior,
            }
        )
    return prepared


def actual_2024_targets(plans: list[dict], eligibles_total: float, outside_key: str = OUTSIDE_PLAN_KEY) -> dict[str, float]:
    """Actual 2024 counts per plan_key (from plans_2024.json's CPSC-derived
    enrollment_2024_03), plus the outside residual = eligibles - modeled-plan enrollment.
    """
    targets = {plan["plan_key"]: float(plan["enrollment_2024_03"]) for plan in plans}
    landscape_total = sum(targets.values())
    targets[outside_key] = eligibles_total - landscape_total
    return targets


# --- forward model / loss ----------------------------------------------------------


def predicted_2024_counts(
    base_coefficients: dict[str, float],
    prepared_archetypes: list[dict],
    plans: list[dict],
    outside_key: str = OUTSIDE_PLAN_KEY,
) -> dict[str, float]:
    """Predicted aggregate 2024 enrollment counts: sum over archetypes of weight * P(plan|archetype)."""
    totals: dict[str, float] = {plan["plan_key"]: 0.0 for plan in plans}
    totals[outside_key] = 0.0

    for archetype in prepared_archetypes:
        probs = utility.choice_probabilities(
            base_coefficients,
            archetype["segment"],
            archetype["eligible_plans"],
            archetype["renormalized_prior"],
            outside_key,
        )
        weight = archetype["weight"]
        for key, prob in probs.items():
            totals[key] = totals.get(key, 0.0) + weight * prob

    return totals


def size_weighted_squared_error(
    base_coefficients: dict[str, float],
    prepared_archetypes: list[dict],
    plans: list[dict],
    actual_counts: dict[str, float],
    eligibles_total: float,
    outside_key: str = OUTSIDE_PLAN_KEY,
) -> float:
    """sum_k actual_share[k] * (predicted_share[k] - actual_share[k])^2, in share space."""
    predicted_counts = predicted_2024_counts(base_coefficients, prepared_archetypes, plans, outside_key)
    error = 0.0
    for key, actual_count in actual_counts.items():
        actual_share = actual_count / eligibles_total
        predicted_share = predicted_counts.get(key, 0.0) / eligibles_total
        error += actual_share * (predicted_share - actual_share) ** 2
    return error


def loss_function(
    x: np.ndarray,
    prepared_archetypes: list[dict],
    plans: list[dict],
    actual_counts: dict[str, float],
    eligibles_total: float,
    prior_vector: np.ndarray,
    l2_lambda: float,
    outside_key: str = OUTSIDE_PLAN_KEY,
) -> float:
    coefficients = vector_to_coefficients(x)
    fit_error = size_weighted_squared_error(coefficients, prepared_archetypes, plans, actual_counts, eligibles_total, outside_key)
    l2_penalty = l2_lambda * float(np.sum((x - prior_vector) ** 2))
    return fit_error + l2_penalty


# --- fit metrics ----------------------------------------------------------------------


def compute_fit_metrics(
    base_coefficients: dict[str, float],
    prepared_archetypes: list[dict],
    plans: list[dict],
    actual_counts: dict[str, float],
    eligibles_total: float,
    outside_key: str = OUTSIDE_PLAN_KEY,
) -> dict:
    predicted_counts = predicted_2024_counts(base_coefficients, prepared_archetypes, plans, outside_key)

    per_key_errors = []
    weights = []
    plan_errors = []
    for key, actual_count in actual_counts.items():
        actual_share = actual_count / eligibles_total
        predicted_share = predicted_counts.get(key, 0.0) / eligibles_total
        abs_err_pp = abs(predicted_share - actual_share) * 100
        per_key_errors.append(abs_err_pp)
        weights.append(actual_count)
        if key != outside_key:
            plan_errors.append(
                {
                    "plan_key": key,
                    "actual_share_pp": round(actual_share * 100, 6),
                    "predicted_share_pp": round(predicted_share * 100, 6),
                    "abs_error_pp": round(abs_err_pp, 6),
                }
            )

    total_weight = sum(weights)
    size_weighted_mae_pp = sum(e * w for e, w in zip(per_key_errors, weights)) / total_weight

    outside_actual_share = actual_counts[outside_key] / eligibles_total
    outside_predicted_share = predicted_counts.get(outside_key, 0.0) / eligibles_total
    outside_error_pp = abs(outside_predicted_share - outside_actual_share) * 100

    plan_errors.sort(key=lambda r: -r["abs_error_pp"])

    return {
        "size_weighted_mae_pp": round(size_weighted_mae_pp, 6),
        "outside_share_actual_pp": round(outside_actual_share * 100, 6),
        "outside_share_predicted_pp": round(outside_predicted_share * 100, 6),
        "outside_share_error_pp": round(outside_error_pp, 6),
        "worst_5_plans_by_abs_error": plan_errors[:5],
        "n_plans": len(plan_errors),
    }


# --- optimizer ----------------------------------------------------------------------


def _starting_points(
    anchors: list[dict[str, float]], bounds: list[tuple[float, float]], n_starts: int, seed: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Build (x0, l2_prior_vector) pairs, one per start.

    Start 0 is its anchor unperturbed; every other start is a small seeded
    perturbation of its own anchor (scaled by START_PERTURBATION_SCALES,
    fraction of that coefficient's bound half-width). Each start's L2
    regularization pull target is that same anchor -- see START_ANCHORS /
    STRONG_INERTIA_PRIOR_COEFFICIENTS docstring notes for why two distinct
    documented-prior anchors are used instead of jittering once around one.
    """
    rng = np.random.default_rng(seed)
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])

    starts: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(n_starts):
        anchor = anchors[i % len(anchors)]
        anchor_vector = np.clip(coefficients_to_vector(anchor), lo, hi)
        scale_fraction = START_PERTURBATION_SCALES[i % len(START_PERTURBATION_SCALES)]
        if scale_fraction <= 0:
            x0 = anchor_vector
        else:
            scale = scale_fraction * (hi - lo) / 2.0
            x0 = np.clip(anchor_vector + rng.normal(loc=0.0, scale=scale), lo, hi)
        starts.append((x0, anchor_vector))
    return starts


def fit_coefficients(
    prepared_archetypes: list[dict],
    plans: list[dict],
    actual_counts: dict[str, float],
    eligibles_total: float,
    outside_key: str = OUTSIDE_PLAN_KEY,
    n_starts: int = N_STARTS,
    seed: int = settings.SEED,
    l2_lambda: float = L2_LAMBDA,
    max_iter: int = MAX_ITER,
) -> dict:
    """Multi-start L-BFGS-B fit. Returns a dict with the winning coefficients
    plus per-start optimizer diagnostics (for coefficients.json metadata).
    """
    bounds = bounds_vector()
    starts = _starting_points(START_ANCHORS, bounds, n_starts, seed)

    per_start = []
    best = None
    for i, (x0, prior_vector) in enumerate(starts):
        args = (prepared_archetypes, plans, actual_counts, eligibles_total, prior_vector, l2_lambda, outside_key)
        result = minimize(
            loss_function,
            x0,
            args=args,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": max_iter},
        )
        record = {
            "start_index": i,
            "x0": vector_to_coefficients(x0),
            "l2_prior_anchor": vector_to_coefficients(prior_vector),
            "final_loss": float(result.fun),
            "iterations": int(result.nit),
            "converged": bool(result.success),
            "message": str(result.message),
        }
        per_start.append(record)
        if best is None or result.fun < best.fun:
            best = result
            best_index = i

    return {
        "coefficients": vector_to_coefficients(best.x),
        "best_start_index": best_index,
        "final_loss": float(best.fun),
        "iterations": int(best.nit),
        "converged": bool(best.success),
        "per_start": per_start,
        "n_starts": n_starts,
        "seed": seed,
        "l2_lambda": l2_lambda,
        "method": "L-BFGS-B",
    }


# --- I/O + orchestration --------------------------------------------------------------


def _load_archetypes() -> list[dict]:
    return json.loads((settings.PROCESSED_DIR / "archetypes.json").read_text())["archetypes"]


def _load_plans_2024() -> tuple[dict, list[dict]]:
    result = json.loads((settings.PROCESSED_DIR / f"plans_{settings.YEAR1}.json").read_text())
    return result["metadata"], result["plans"]


def _attribute_scaling_metadata() -> dict:
    return {
        "premium_total_formula": "premium_part_c + premium_part_d",
        "premium_divisor": utility.PREMIUM_DIVISOR,
        "premium_scaling_note": "coefficient applies to premium_total / premium_divisor (i.e. per $10 of monthly premium)",
        "moop_divisor": utility.MOOP_DIVISOR,
        "moop_scaling_note": "coefficient applies to moop_inn / moop_divisor (i.e. per $1,000 of in-network MOOP)",
        "star_rating_center": utility.STAR_RATING_CENTER,
        "star_scaling_note": "coefficient applies to (star_rating - star_rating_center)",
        "vision_hearing_formula": "(has_vision + has_hearing_aids) / 2",
        "is_ppo_definition": "plan_type in {PPO, Regional PPO} (see plan_attributes.normalize_plan_type)",
        "inertia_definition": "b_inertia * prior_plan_year1 probability for that plan/outside, after choice_sets.renormalize_prior_plan",
        "outside_option_utility_formula": "b_outside + b_inertia * prior_prob(archetype, outside)",
    }


def calibrate() -> dict:
    """Run the full Year-1 calibration and return the coefficients.json dict (not yet written)."""
    archetypes = _load_archetypes()
    _, plans = _load_plans_2024()

    eligibles_total = sum(float(a["weight"]) for a in archetypes)
    prepared = prepare_archetype_choice_data(archetypes, plans, OUTSIDE_PLAN_KEY)
    actual_counts = actual_2024_targets(plans, eligibles_total, OUTSIDE_PLAN_KEY)

    fit_result = fit_coefficients(prepared, plans, actual_counts, eligibles_total, OUTSIDE_PLAN_KEY)
    coefficients = fit_result["coefficients"]

    fit_metrics = compute_fit_metrics(coefficients, prepared, plans, actual_counts, eligibles_total, OUTSIDE_PLAN_KEY)

    metadata = {
        "phase": 3,
        "year1": settings.YEAR1,
        "seed": settings.SEED,
        "generated_from": {
            "archetypes_file": "archetypes.json",
            "plans_file": f"plans_{settings.YEAR1}.json",
            "n_archetypes": len(archetypes),
            "n_plans": len(plans),
        },
        "calibration": {
            "method": fit_result["method"],
            "loss_function": (
                "size-weighted squared error between predicted and actual 2024 aggregate "
                "shares (weight = actual share), plus l2_lambda * sum((x - l2_prior_anchor)^2) "
                "pulling each start toward its own documented economic-prior anchor "
                "(see calibration.prior_coefficients / strong_inertia_prior_coefficients and "
                "each per_start entry's l2_prior_anchor)"
            ),
            "l2_lambda": fit_result["l2_lambda"],
            "n_starts": fit_result["n_starts"],
            "seed": fit_result["seed"],
            "best_start_index": fit_result["best_start_index"],
            "final_loss": fit_result["final_loss"],
            "iterations": fit_result["iterations"],
            "converged": fit_result["converged"],
            "prior_coefficients": PRIOR_COEFFICIENTS,
            "strong_inertia_prior_coefficients": STRONG_INERTIA_PRIOR_COEFFICIENTS,
            "bounds": {name: list(BOUNDS[name]) for name in utility.BASE_COEFFICIENT_NAMES},
            "per_start": fit_result["per_start"],
        },
        "fit_metrics_year1": fit_metrics,
    }

    return {
        "metadata": metadata,
        "base_coefficients": coefficients,
        "segment_multipliers": utility.SEGMENT_MULTIPLIERS,
        "attribute_scaling": _attribute_scaling_metadata(),
        "choice_set_rules": choice_sets.CHOICE_SET_RULES,
        "outside_option_key": OUTSIDE_PLAN_KEY,
    }


def build(output_path: Path | None = None) -> dict:
    result = calibrate()
    CoefficientsFile.model_validate(result)  # fail loudly on a malformed artifact

    dest = output_path if output_path is not None else settings.PROCESSED_DIR / "coefficients.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    return result


if __name__ == "__main__":
    result = build()
    coeffs = result["base_coefficients"]
    fit = result["metadata"]["fit_metrics_year1"]
    calib = result["metadata"]["calibration"]
    print("base_coefficients:")
    for name, value in coeffs.items():
        print(f"  {name:<18} {value: .6f}")
    print(
        f"calibration: {calib['n_starts']} starts, best_start_index={calib['best_start_index']}, "
        f"final_loss={calib['final_loss']:.8f}, iterations={calib['iterations']}, converged={calib['converged']}"
    )
    print(
        f"Y1 fit: size_weighted_mae_pp={fit['size_weighted_mae_pp']:.4f}  "
        f"outside_share_error_pp={fit['outside_share_error_pp']:.4f} "
        f"(actual={fit['outside_share_actual_pp']:.4f}, predicted={fit['outside_share_predicted_pp']:.4f})"
    )
    print("worst 5 plans by abs error:")
    for row in fit["worst_5_plans_by_abs_error"]:
        print(f"  {row['plan_key']:<12} actual={row['actual_share_pp']:.4f}pp predicted={row['predicted_share_pp']:.4f}pp err={row['abs_error_pp']:.4f}pp")
