"""Tests for llm/run_persona_pass.py — Phase 4 orchestration entrypoint.

Everything here runs against the real committed 80-archetype dataset (all
Phase 1-3 inputs are committed, deterministic files) with a fully mocked
OpenAI client (``GenericFakeClient`` below) -- no network access and no
OPENAI_API_KEY is ever required, matching llm/client.py's own test
discipline. This is the required "full 80-archetype pass vs. a mocked LLM
client" coverage: call-count accounting (160 planned calls), warm-cache
rerun (0 new calls), the pre-flight budget assertion, and deterministic
output given fixed mock responses.
"""

from __future__ import annotations

import json

import pytest

from choice_model import predict
from config.settings import settings
from llm import run_persona_pass as rpp

N_ARCHETYPES = 80
CALLS_PER_ARCHETYPE = 2
PLANNED_CALLS = N_ARCHETYPES * CALLS_PER_ARCHETYPE  # 160


def _real_data_available() -> bool:
    return (
        (settings.PROCESSED_DIR / "archetypes.json").exists()
        and (settings.PROCESSED_DIR / f"plans_{settings.YEAR1}.json").exists()
        and (settings.PROCESSED_DIR / f"plans_{settings.YEAR2}.json").exists()
        and (settings.PROCESSED_DIR / "coefficients.json").exists()
        and (settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet").exists()
    )


def _load_real_inputs() -> dict:
    return rpp._load_real_inputs()


# --------------------------------------------------------------------------
# Generic fake OpenAI structured-output client: derives a schema-valid
# response purely from the request's json_schema (no per-call scripting
# needed for all 160 real-pass calls), so its output is a deterministic
# pure function of the request content.
# --------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.refusal = None


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeUsage:
    def __init__(self, total_tokens=10):
        self.total_tokens = total_tokens


class _FakeResponse:
    def __init__(self, content, response_id):
        self.id = response_id
        self.choices = [_FakeChoice(_FakeMessage(content))]
        self.usage = _FakeUsage()


class GenericFakeCompletions:
    def __init__(self):
        self.calls: list[dict] = []
        self._counter = 0

    def create(self, **kwargs):
        self.calls.append(kwargs)
        self._counter += 1
        schema = kwargs["response_format"]["json_schema"]["schema"]
        if "ranked_plan_keys" in schema["properties"]:
            alt_keys = schema["properties"]["ranked_plan_keys"]["items"]["enum"]
            content = json.dumps(
                {
                    "ranked_plan_keys": list(alt_keys),
                    "switching_propensity": 0.4,
                    "rationale": "This plan best fits my needs based on cost and coverage.",
                }
            )
        else:
            content = json.dumps(
                {
                    "name": f"Persona {self._counter}",
                    "backstory": "A fictional Medicare beneficiary weighing their 2025 coverage options.",
                }
            )
        return _FakeResponse(content, response_id=f"fake-{self._counter}")


class ExplodingCompletions:
    """Used to prove "no network call happens" -- any call raises."""

    def create(self, **kwargs):
        raise AssertionError("no network call should have been made")


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class GenericFakeClient:
    def __init__(self):
        self.completions = GenericFakeCompletions()
        self.chat = _FakeChat(self.completions)


class ExplodingFakeClient:
    def __init__(self):
        self.completions = ExplodingCompletions()
        self.chat = _FakeChat(self.completions)


def _llm_client(tmp_path, client=None, max_calls=500):
    from llm.client import LLMClient

    return LLMClient(client=client or GenericFakeClient(), model="gpt-5.6-luna", cache_dir=tmp_path, max_calls=max_calls)


# --------------------------------------------------------------------------
# Small synthetic tests (fast, no real data required)
# --------------------------------------------------------------------------


def test_sanitize_ranked_plan_keys_filters_dedupes_and_pads_missing():
    alternatives = ["A", "B", "C", "OUT"]
    raw = ["B", "B", "ZZZ", "A"]  # dup, unknown key, missing C and OUT
    result = rpp._sanitize_ranked_plan_keys(raw, alternatives)
    assert result == ["B", "A", "C", "OUT"]
    assert set(result) == set(alternatives)


def test_sanitize_ranked_plan_keys_empty_input_falls_back_to_original_order():
    alternatives = ["A", "B"]
    assert rpp._sanitize_ranked_plan_keys([], alternatives) == ["A", "B"]


def test_clamp01():
    assert rpp._clamp01(-1.0) == 0.0
    assert rpp._clamp01(2.0) == 1.0
    assert rpp._clamp01(0.4) == 0.4


def test_planned_call_count_is_160_and_within_budget():
    assert PLANNED_CALLS == 160
    assert PLANNED_CALLS <= settings.MAX_LLM_CALLS


# --------------------------------------------------------------------------
# Full 80-archetype pass against real committed data + mocked LLM client
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_full_pass_call_count_accounting(tmp_path):
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    inputs = _load_real_inputs()
    llm_client = _llm_client(tmp_path)

    result = rpp.run_persona_pass(llm_client, **inputs)

    assert len(result["personas"]) == N_ARCHETYPES
    assert llm_client.calls_made == PLANNED_CALLS
    assert llm_client.cache_hits == 0
    assert llm_client.calls_made <= settings.MAX_LLM_CALLS
    budget = result["y2_predictions"]["metadata"]["budget"]
    assert budget["calls_made"] == PLANNED_CALLS
    assert budget["projected_new_calls_preflight"] == PLANNED_CALLS


@pytest.mark.integration
def test_warm_cache_rerun_makes_zero_new_calls(tmp_path):
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    inputs = _load_real_inputs()

    warm_client = _llm_client(tmp_path)
    rpp.run_persona_pass(warm_client, **inputs)
    assert warm_client.calls_made == PLANNED_CALLS

    cold_client = _llm_client(tmp_path, client=ExplodingFakeClient())
    result = rpp.run_persona_pass(cold_client, **inputs)

    assert cold_client.calls_made == 0
    assert cold_client.cache_hits == PLANNED_CALLS
    assert result["y2_predictions"]["metadata"]["budget"]["projected_new_calls_preflight"] == 0


@pytest.mark.integration
def test_budget_preflight_raises_before_any_network_call(tmp_path):
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    inputs = _load_real_inputs()
    # Fewer than the 160 planned calls -- must fail the pre-flight check.
    llm_client = _llm_client(tmp_path, max_calls=100)

    with pytest.raises(rpp.ProjectedBudgetExceededError):
        rpp.run_persona_pass(llm_client, **inputs)

    assert llm_client.calls_made == 0  # pre-flight check happens before any call


@pytest.mark.integration
def test_budget_preflight_passes_when_cache_already_covers_the_shortfall(tmp_path):
    """If enough of the 160 requests are already cache hits, a low max_calls
    budget should NOT trip the pre-flight check."""
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    inputs = _load_real_inputs()

    warm_client = _llm_client(tmp_path, max_calls=500)
    rpp.run_persona_pass(warm_client, **inputs)

    # Now fully warm: a client with max_calls=0 should succeed (0 projected new calls).
    tiny_budget_client = _llm_client(tmp_path, client=ExplodingFakeClient(), max_calls=0)
    result = rpp.run_persona_pass(tiny_budget_client, **inputs)
    assert result["y2_predictions"]["metadata"]["budget"]["calls_made"] == 0


@pytest.mark.integration
def test_deterministic_output_given_fixed_mock_responses(tmp_path):
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    inputs = _load_real_inputs()

    result_a = rpp.run_persona_pass(_llm_client(tmp_path / "a"), **inputs)
    result_b = rpp.run_persona_pass(_llm_client(tmp_path / "b"), **inputs)

    assert result_a["personas"] == result_b["personas"]
    assert result_a["y2_predictions"]["per_archetype"] == result_b["y2_predictions"]["per_archetype"]
    assert result_a["y2_predictions"]["aggregate_shares"] == result_b["y2_predictions"]["aggregate_shares"]


@pytest.mark.integration
def test_personas_json_shape(tmp_path):
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    inputs = _load_real_inputs()
    llm_client = _llm_client(tmp_path)

    result = rpp.run_persona_pass(llm_client, **inputs)

    ids_seen = set()
    for persona in result["personas"]:
        assert set(persona.keys()) == {
            "id",
            "name",
            "backstory",
            "ranked_plan_keys",
            "switching_propensity",
            "rationale",
            "consideration_set",
        }
        assert persona["id"] not in ids_seen
        ids_seen.add(persona["id"])
        assert isinstance(persona["name"], str) and persona["name"]
        assert isinstance(persona["backstory"], str) and persona["backstory"]
        assert 0.0 <= persona["switching_propensity"] <= 1.0
        assert isinstance(persona["rationale"], str)
        assert len(persona["consideration_set"]) <= 8
        # ranked_plan_keys must be exactly consideration_set + outside, permuted
        assert set(persona["ranked_plan_keys"]) == set(persona["consideration_set"]) | {predict.OUTSIDE_KEY_YEAR2}
        assert len(persona["ranked_plan_keys"]) == len(set(persona["ranked_plan_keys"]))

    assert len(ids_seen) == N_ARCHETYPES


@pytest.mark.integration
def test_y2_predictions_json_shape(tmp_path):
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    inputs = _load_real_inputs()
    llm_client = _llm_client(tmp_path)

    result = rpp.run_persona_pass(llm_client, **inputs)
    y2 = result["y2_predictions"]

    assert y2["metadata"]["alpha"] == pytest.approx(0.35)
    assert y2["metadata"]["outside_option_key"] == predict.OUTSIDE_KEY_YEAR2
    assert y2["metadata"]["budget"]["max_calls"] == 500

    assert set(y2["aggregate_shares"].keys()) == {"logit_only", "blended"}
    assert sum(y2["aggregate_shares"]["logit_only"].values()) == pytest.approx(1.0)
    assert sum(y2["aggregate_shares"]["blended"].values()) == pytest.approx(1.0)

    assert len(y2["per_archetype"]) == N_ARCHETYPES
    for aid, per in y2["per_archetype"].items():
        assert set(per.keys()) == {"logit_probs", "blended_probs"}
        assert sum(per["logit_probs"].values()) == pytest.approx(1.0)
        assert sum(per["blended_probs"].values()) == pytest.approx(1.0)


@pytest.mark.integration
def test_build_writes_artifacts_to_output_dir(tmp_path):
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    from llm.client import LLMClient

    llm_client = LLMClient(client=GenericFakeClient(), model="gpt-5.6-luna", cache_dir=tmp_path / "cache", max_calls=500)
    out_dir = tmp_path / "out"

    result = rpp.build(llm_client=llm_client, output_dir=out_dir)

    personas_path = out_dir / rpp.PERSONAS_FILENAME
    predictions_path = out_dir / rpp.PREDICTIONS_FILENAME
    assert personas_path.exists()
    assert predictions_path.exists()

    written_personas = json.loads(personas_path.read_text())
    assert len(written_personas["personas"]) == N_ARCHETYPES
    written_predictions = json.loads(predictions_path.read_text())
    assert written_predictions["metadata"]["phase"] == 4
    assert result["personas"] == written_personas["personas"]
