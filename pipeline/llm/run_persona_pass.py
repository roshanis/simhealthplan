"""Phase 4 entrypoint: the LLM persona pass (``make personas``).

For each of the 80 archetypes: builds the pure Year-2 logit baseline
(``choice_model.predict``), constructs a consideration set + two structured
prompts (``llm.persona_prompts``), makes one CHOICE call and one BACKSTORY
call through the cache-first, budget-capped ``llm.client.LLMClient``, blends
the CHOICE output into the logit model (``llm.blend``), and writes:

  * ``data/processed/personas.json`` -- one record per archetype: id, name,
    backstory, ranked_plan_keys, switching_propensity, rationale,
    consideration_set.
  * ``data/processed/y2_predictions.json`` -- metadata (model, alpha, budget
    stats), per-archetype logit-only + blended probs, and aggregate
    predicted 2025 shares side by side (logit_only vs. blended).

Budget: a pre-flight check (``_assert_budget_ok``) computes how many of the
160 planned requests (80 archetypes x 2 prompts) would actually be *new*
network calls (i.e. aren't already cache hits) and raises
``ProjectedBudgetExceededError`` -- before a single request is sent -- if
that would exceed the ``LLMClient``'s remaining budget. This is a stronger
guarantee than ``LLMClient``'s own per-call ``BudgetExceededError`` (which
only fires mid-run, after any calls already made in this run are spent).
"""

from __future__ import annotations

import json
from pathlib import Path

from choice_model import choice_sets, predict
from config.settings import settings
from llm import blend, persona_prompts
from llm.client import BudgetExceededError, LLMClient
from llm.client import cache_key as llm_cache_key

CALLS_PER_ARCHETYPE = 2  # 1 CHOICE call + 1 BACKSTORY call

PERSONAS_FILENAME = "personas.json"
PREDICTIONS_FILENAME = "y2_predictions.json"


class ProjectedBudgetExceededError(BudgetExceededError):
    """Raised by the pre-flight budget check (before any network call is
    attempted) when the projected new-call count for this persona pass
    would exceed the LLM client's remaining call budget."""


# --- small pure helpers -----------------------------------------------------------


def _index_by_plan_key(plans: list[dict]) -> dict[str, dict]:
    return {plan["plan_key"]: plan for plan in plans}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _sanitize_ranked_plan_keys(raw_ranked: list, alternative_keys: list[str]) -> list[str]:
    """A valid permutation of `alternative_keys`, regardless of what the LLM
    actually returned: keeps only recognized, non-duplicate keys from
    `raw_ranked` (in the order given), then appends any alternative keys the
    model omitted, in their original (consideration-set) order. Guarantees
    downstream ``blend.rank_bonus``/``choice_response_schema`` consumers
    always see a complete, valid ranking."""
    valid = set(alternative_keys)
    seen: set[str] = set()
    cleaned: list[str] = []
    for key in raw_ranked:
        if key in valid and key not in seen:
            cleaned.append(key)
            seen.add(key)
    for key in alternative_keys:
        if key not in seen:
            cleaned.append(key)
            seen.add(key)
    return cleaned


# --- budget pre-flight -------------------------------------------------------------


def _is_cache_hit(llm_client: LLMClient, system: str, user: str, schema_version: str) -> bool:
    key = llm_cache_key(llm_client.model, system, user, schema_version)
    return (llm_client.cache_dir / f"{key}.json").exists()


def _assert_budget_ok(llm_client: LLMClient, prompt_specs: list[dict]) -> int:
    """Returns the projected new (non-cache-hit) call count; raises
    ``ProjectedBudgetExceededError`` first if it would exceed the client's
    remaining budget. No network call is made by this check."""
    projected_new = sum(0 if _is_cache_hit(llm_client, spec["system"], spec["user"], spec["schema_version"]) else 1 for spec in prompt_specs)
    remaining = llm_client.max_calls - llm_client.calls_made
    if projected_new > remaining:
        raise ProjectedBudgetExceededError(
            f"Persona pass would need {projected_new} new LLM calls but only {remaining} remain "
            f"in the budget ({llm_client.calls_made}/{llm_client.max_calls} already used)."
        )
    return projected_new


# --- orchestration -----------------------------------------------------------------


def run_persona_pass(
    llm_client: LLMClient,
    archetypes: list[dict],
    plans_2024: list[dict],
    plans_2025: list[dict],
    coefficients: dict,
    crosswalk_map: dict[str, dict],
    outside_key_year1: str = predict.OUTSIDE_KEY_YEAR1,
    outside_key_year2: str = predict.OUTSIDE_KEY_YEAR2,
) -> dict:
    """Runs the full persona pass. Returns ``{"personas": [...], "y2_predictions": {...}}``
    (not yet written to disk -- see ``build`` below)."""
    base_coefficients = coefficients["base_coefficients"]
    plans_2024_by_key = _index_by_plan_key(plans_2024)
    plans_2025_by_key = _index_by_plan_key(plans_2025)

    logit_result = predict.predict_all(archetypes, plans_2025, base_coefficients, crosswalk_map, outside_key_year1, outside_key_year2)

    # Build every prompt spec up front so the budget pre-flight check sees
    # the full planned request set before any network call is attempted.
    choice_specs: dict[str, dict] = {}
    backstory_specs: dict[str, dict] = {}
    consideration_sets: dict[str, list[str]] = {}
    for archetype in archetypes:
        aid = archetype["id"]
        per = logit_result["per_archetype"][aid]
        consideration = persona_prompts.build_consideration_set(
            per["eligible_plan_keys"], per["probs"], per["renormalized_prior"], plans_2025, outside_key_year2
        )
        consideration_sets[aid] = consideration
        choice_specs[aid] = persona_prompts.build_choice_prompt(
            archetype, plans_2024_by_key, plans_2025_by_key, consideration, outside_key_year1, outside_key_year2
        )
        backstory_specs[aid] = persona_prompts.build_backstory_prompt(archetype)

    all_specs = [*choice_specs.values(), *backstory_specs.values()]
    projected_new_calls = _assert_budget_ok(llm_client, all_specs)

    personas: list[dict] = []
    blended_by_archetype: dict[str, dict[str, float]] = {}

    for archetype in archetypes:
        aid = archetype["id"]
        choice_spec = choice_specs[aid]
        backstory_spec = backstory_specs[aid]

        choice_result = llm_client.complete_structured(
            choice_spec["prompt_key"], choice_spec["system"], choice_spec["user"], choice_spec["response_schema"], choice_spec["schema_version"]
        )
        backstory_result = llm_client.complete_structured(
            backstory_spec["prompt_key"],
            backstory_spec["system"],
            backstory_spec["user"],
            backstory_spec["response_schema"],
            backstory_spec["schema_version"],
        )

        ranked_plan_keys = _sanitize_ranked_plan_keys(choice_result.get("ranked_plan_keys", []), choice_spec["alternative_keys"])
        switching_propensity = _clamp01(float(choice_result.get("switching_propensity", 0.5)))
        rationale = str(choice_result.get("rationale", ""))

        per = logit_result["per_archetype"][aid]
        eligible_plans = choice_sets.eligible_plans(archetype, plans_2025)
        blended_probs = blend.blended_choice_probabilities(
            base_coefficients,
            archetype["attitude_segment"],
            eligible_plans,
            per["renormalized_prior"],
            outside_key_year2,
            ranked_plan_keys,
            switching_propensity,
        )
        blended_by_archetype[aid] = blended_probs

        personas.append(
            {
                "id": aid,
                "name": str(backstory_result.get("name", "")),
                "backstory": str(backstory_result.get("backstory", "")),
                "ranked_plan_keys": ranked_plan_keys,
                "switching_propensity": switching_propensity,
                "rationale": rationale,
                "consideration_set": consideration_sets[aid],
            }
        )

    aggregate_blended = predict.aggregate_weighted_shares(archetypes, blended_by_archetype)

    y2_predictions = {
        "metadata": {
            "phase": 4,
            "model": llm_client.model,
            "alpha": blend.ALPHA,
            "outside_option_key": outside_key_year2,
            "generated_from": {
                "n_archetypes": len(archetypes),
                "n_plans_2025": len(plans_2025),
            },
            "budget": {
                "max_calls": llm_client.max_calls,
                "calls_made": llm_client.calls_made,
                "cache_hits": llm_client.cache_hits,
                "projected_new_calls_preflight": projected_new_calls,
                "calls_per_archetype": CALLS_PER_ARCHETYPE,
            },
        },
        "per_archetype": {
            aid: {
                "logit_probs": logit_result["per_archetype"][aid]["probs"],
                "blended_probs": blended_by_archetype[aid],
            }
            for aid in blended_by_archetype
        },
        "aggregate_shares": {
            "logit_only": logit_result["aggregate_shares"],
            "blended": aggregate_blended,
        },
    }

    return {"personas": personas, "y2_predictions": y2_predictions}


# --- real-file I/O -----------------------------------------------------------------


def _load_real_inputs() -> dict:
    archetypes = json.loads((settings.PROCESSED_DIR / "archetypes.json").read_text())["archetypes"]
    plans_2024 = json.loads((settings.PROCESSED_DIR / f"plans_{settings.YEAR1}.json").read_text())["plans"]
    plans_2025 = json.loads((settings.PROCESSED_DIR / f"plans_{settings.YEAR2}.json").read_text())["plans"]
    coefficients = json.loads((settings.PROCESSED_DIR / "coefficients.json").read_text())
    crosswalk_map = predict.load_crosswalk_map()
    return {
        "archetypes": archetypes,
        "plans_2024": plans_2024,
        "plans_2025": plans_2025,
        "coefficients": coefficients,
        "crosswalk_map": crosswalk_map,
    }


def build(llm_client: LLMClient | None = None, output_dir: Path | None = None) -> dict:
    """Runs the full persona pass against the real committed data files and
    writes ``personas.json`` / ``y2_predictions.json``. Returns the same
    dict as ``run_persona_pass``."""
    inputs = _load_real_inputs()
    client = llm_client if llm_client is not None else LLMClient()

    result = run_persona_pass(client, **inputs)

    dest_dir = output_dir if output_dir is not None else settings.PROCESSED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    personas_payload = {
        "metadata": {
            "phase": 4,
            "seed": settings.SEED,
            "model": client.model,
            "n_archetypes": len(result["personas"]),
        },
        "personas": result["personas"],
    }
    (dest_dir / PERSONAS_FILENAME).write_text(json.dumps(personas_payload, indent=2, sort_keys=True) + "\n")
    (dest_dir / PREDICTIONS_FILENAME).write_text(json.dumps(result["y2_predictions"], indent=2, sort_keys=True) + "\n")

    return result


if __name__ == "__main__":
    out = build()
    budget = out["y2_predictions"]["metadata"]["budget"]
    print(f"{PERSONAS_FILENAME}: {len(out['personas'])} archetypes")
    print(f"calls_made={budget['calls_made']} cache_hits={budget['cache_hits']} " f"projected_new_calls_preflight={budget['projected_new_calls_preflight']} max_calls={budget['max_calls']}")
    logit_shares = out["y2_predictions"]["aggregate_shares"]["logit_only"]
    blended_shares = out["y2_predictions"]["aggregate_shares"]["blended"]
    deltas = sorted(
        ((key, blended_shares.get(key, 0.0) - logit_shares.get(key, 0.0)) for key in logit_shares),
        key=lambda item: -abs(item[1]),
    )
    print("top 5 blended-vs-logit share movers:")
    for key, delta in deltas[:5]:
        print(f"  {key:<28} logit={logit_shares[key] * 100:7.3f}pp blended={blended_shares.get(key, 0.0) * 100:7.3f}pp delta={delta * 100:+7.3f}pp")
