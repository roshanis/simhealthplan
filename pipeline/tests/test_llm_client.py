"""Tests for the LLM client infrastructure (pipeline/llm/client.py).

TDD: written before llm/client.py exists — expected to fail on import until
LLMClient, BudgetExceededError, SchemaValidationError, and cache_key are
implemented.

Everything here is mocked: no network access and no OPENAI_API_KEY is ever
required. Dependency injection (``client=`` / ``client_factory=``) keeps the
real ``openai.OpenAI()`` constructor out of the test process entirely except
where a test explicitly wants to prove it was *not* called.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import openai
import pytest

from llm.client import (
    BudgetExceededError,
    LLMClient,
    SchemaValidationError,
    cache_key,
)

FIXTURES = Path(__file__).parent / "fixtures"
RESPONSE_SCHEMA = json.loads((FIXTURES / "llm_response_schema.json").read_text())
SAMPLE_RESPONSE = json.loads((FIXTURES / "llm_sample_response.json").read_text())

SYSTEM = "You are a Medicare beneficiary persona choosing a plan."
USER = "Given these three plans, which do you choose?"
SCHEMA_VERSION = "v1"
MODEL = "gpt-5.6-luna"


# --------------------------------------------------------------------------
# Fake OpenAI SDK objects — mimic just enough of the real response shape
# (resp.choices[0].message.content / .refusal, resp.id, resp.usage.total_tokens)
# --------------------------------------------------------------------------


class FakeMessage:
    def __init__(self, content, refusal=None):
        self.content = content
        self.refusal = refusal


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeUsage:
    def __init__(self, total_tokens):
        self.total_tokens = total_tokens


class FakeChatCompletion:
    def __init__(self, content, response_id="chatcmpl-test", total_tokens=42, usage=True):
        self.id = response_id
        self.choices = [FakeChoice(FakeMessage(content))]
        self.usage = FakeUsage(total_tokens) if usage else None


def valid_completion(response_id="chatcmpl-test", total_tokens=42):
    return FakeChatCompletion(json.dumps(SAMPLE_RESPONSE), response_id=response_id, total_tokens=total_tokens)


def invalid_json_completion(response_id="chatcmpl-bad"):
    return FakeChatCompletion("this is not valid json {{{", response_id=response_id)


class FakeChatCompletions:
    """Stand-in for ``client.chat.completions``; ``create`` pops canned responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeChatCompletions.create called more times than responses were queued")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeChat:
    def __init__(self, completions: FakeChatCompletions):
        self.completions = completions


class FakeOpenAIClient:
    def __init__(self, responses):
        self.completions = FakeChatCompletions(responses)
        self.chat = FakeChat(self.completions)


def transient_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))


# --------------------------------------------------------------------------
# Cache miss / hit
# --------------------------------------------------------------------------


def test_cache_miss_calls_api_writes_file_and_returns_parsed_dict(tmp_path):
    fake_client = FakeOpenAIClient([valid_completion()])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    result = llm.complete_structured(
        prompt_key="plan_choice",
        system=SYSTEM,
        user=USER,
        response_schema=RESPONSE_SCHEMA,
        schema_version=SCHEMA_VERSION,
    )

    assert result == SAMPLE_RESPONSE
    assert llm.calls_made == 1
    assert llm.cache_hits == 0
    assert len(fake_client.completions.calls) == 1

    key = cache_key(MODEL, SYSTEM, USER, SCHEMA_VERSION)
    cache_file = tmp_path / f"{key}.json"
    assert cache_file.exists()

    payload = json.loads(cache_file.read_text())
    assert list(payload.keys()) == ["key", "request", "response", "response_id", "created_at"]
    assert payload["key"] == {"model": MODEL, "prompt_key": "plan_choice", "schema_version": SCHEMA_VERSION}
    assert payload["request"] == {"system": SYSTEM, "user": USER}
    assert payload["response"] == SAMPLE_RESPONSE
    assert payload["response_id"] == "chatcmpl-test"
    assert isinstance(payload["created_at"], str) and payload["created_at"]


def test_cache_hit_makes_no_api_call_and_never_constructs_client(tmp_path):
    fake_client = FakeOpenAIClient([valid_completion()])
    factory_calls = []

    def factory():
        factory_calls.append(1)
        return fake_client

    llm = LLMClient(client_factory=factory, model=MODEL, cache_dir=tmp_path, max_calls=10)

    first = llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)
    assert first == SAMPLE_RESPONSE
    assert len(factory_calls) == 1  # lazily built on the first (and only) miss
    assert llm.calls_made == 1

    second = llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    assert second == SAMPLE_RESPONSE
    assert llm.calls_made == 1  # unchanged: served from cache
    assert llm.cache_hits == 1
    assert len(factory_calls) == 1  # factory not invoked again
    assert len(fake_client.completions.calls) == 1  # no second network call


def test_cache_hit_across_separate_client_instances_needs_no_client_at_all(tmp_path):
    """A fully cold LLMClient (no client, no factory override) still succeeds
    against a pre-warmed cache — proving the default openai.OpenAI() factory
    is never touched on a hit."""
    warm_client = FakeOpenAIClient([valid_completion()])
    warm = LLMClient(client=warm_client, model=MODEL, cache_dir=tmp_path, max_calls=10)
    warm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    def exploding_factory():
        raise AssertionError("default client factory must not be invoked on a cache hit")

    cold = LLMClient(client_factory=exploding_factory, model=MODEL, cache_dir=tmp_path, max_calls=10)
    result = cold.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    assert result == SAMPLE_RESPONSE
    assert cold.calls_made == 0
    assert cold.cache_hits == 1


# --------------------------------------------------------------------------
# Cache key sensitivity
# --------------------------------------------------------------------------


def test_different_schema_version_produces_different_cache_key(tmp_path):
    fake_client = FakeOpenAIClient([valid_completion(), valid_completion(response_id="chatcmpl-2")])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, "v1")
    llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, "v2")

    assert llm.calls_made == 2
    assert cache_key(MODEL, SYSTEM, USER, "v1") != cache_key(MODEL, SYSTEM, USER, "v2")
    files = sorted(tmp_path.glob("*.json"))
    assert len(files) == 2


def test_different_model_produces_different_cache_key(tmp_path):
    fake_client_a = FakeOpenAIClient([valid_completion()])
    fake_client_b = FakeOpenAIClient([valid_completion(response_id="chatcmpl-2")])
    llm_a = LLMClient(client=fake_client_a, model="gpt-5.6-luna", cache_dir=tmp_path, max_calls=10)
    llm_b = LLMClient(client=fake_client_b, model="gpt-5.6-luna-mini", cache_dir=tmp_path, max_calls=10)

    llm_a.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)
    llm_b.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    assert cache_key("gpt-5.6-luna", SYSTEM, USER, SCHEMA_VERSION) != cache_key(
        "gpt-5.6-luna-mini", SYSTEM, USER, SCHEMA_VERSION
    )
    files = sorted(tmp_path.glob("*.json"))
    assert len(files) == 2


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------


def test_budget_exceeded_raised_at_boundary(tmp_path):
    fake_client = FakeOpenAIClient(
        [
            valid_completion(response_id="1"),
            FakeChatCompletion(json.dumps({"chosen_plan_id": "H0002-002", "confidence": 0.5, "reasoning": "x"}), response_id="2"),
        ]
    )
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=2)

    llm.complete_structured("plan_choice", SYSTEM, "user-1", RESPONSE_SCHEMA, SCHEMA_VERSION)
    llm.complete_structured("plan_choice", SYSTEM, "user-2", RESPONSE_SCHEMA, SCHEMA_VERSION)
    assert llm.calls_made == 2

    with pytest.raises(BudgetExceededError):
        llm.complete_structured("plan_choice", SYSTEM, "user-3", RESPONSE_SCHEMA, SCHEMA_VERSION)

    # the rejected attempt must not have consumed budget or reached the network
    assert llm.calls_made == 2
    assert len(fake_client.completions.calls) == 2


def test_cache_hits_do_not_consume_budget(tmp_path):
    fake_client = FakeOpenAIClient([valid_completion()])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=1)

    llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)
    assert llm.calls_made == 1

    # budget is exhausted, but repeated identical requests are cache hits and
    # must keep succeeding without ever touching the network again.
    for _ in range(5):
        result = llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)
        assert result == SAMPLE_RESPONSE

    assert llm.calls_made == 1
    assert llm.cache_hits == 5


# --------------------------------------------------------------------------
# Parse-failure corrective retry
# --------------------------------------------------------------------------


def test_invalid_json_triggers_one_corrective_retry_then_succeeds(tmp_path):
    fake_client = FakeOpenAIClient([invalid_json_completion(), valid_completion()])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    result = llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    assert result == SAMPLE_RESPONSE
    assert llm.calls_made == 2  # both attempts count against budget
    assert len(fake_client.completions.calls) == 2

    # the corrective retry must carry an appended corrective instruction
    first_call_user = fake_client.completions.calls[0]["messages"][-1]["content"]
    second_call_user = fake_client.completions.calls[1]["messages"][-1]["content"]
    assert first_call_user == USER
    assert USER in second_call_user
    assert second_call_user != first_call_user

    # cache holds only the successful response
    key = cache_key(MODEL, SYSTEM, USER, SCHEMA_VERSION)
    payload = json.loads((tmp_path / f"{key}.json").read_text())
    assert payload["response"] == SAMPLE_RESPONSE


def test_two_invalid_json_responses_raises_schema_validation_error(tmp_path):
    fake_client = FakeOpenAIClient([invalid_json_completion(), invalid_json_completion(response_id="bad-2")])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    with pytest.raises(SchemaValidationError):
        llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    assert llm.calls_made == 2
    key = cache_key(MODEL, SYSTEM, USER, SCHEMA_VERSION)
    assert not (tmp_path / f"{key}.json").exists()


# --------------------------------------------------------------------------
# call_log.jsonl
# --------------------------------------------------------------------------


def test_call_log_appended_only_on_network_calls(tmp_path):
    fake_client = FakeOpenAIClient([valid_completion(total_tokens=123)])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    log_path = tmp_path / "call_log.jsonl"
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["prompt_key"] == "plan_choice"
    assert entry["model"] == MODEL
    assert "ts" in entry and entry["ts"]
    assert entry["tokens"] == 123

    # a cache hit must not append another line
    llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)
    lines_after_hit = log_path.read_text().strip().splitlines()
    assert len(lines_after_hit) == 1


def test_call_log_entry_omits_tokens_when_usage_unavailable(tmp_path):
    completion = FakeChatCompletion(json.dumps(SAMPLE_RESPONSE), usage=False)
    fake_client = FakeOpenAIClient([completion])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    entry = json.loads((tmp_path / "call_log.jsonl").read_text().strip().splitlines()[0])
    assert "tokens" not in entry


# --------------------------------------------------------------------------
# No API key, warm cache
# --------------------------------------------------------------------------


def test_no_api_key_env_var_warm_cache_still_works(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # warm the cache using an injected fake client (no real key needed here either)
    warm_client = FakeOpenAIClient([valid_completion()])
    warm = LLMClient(client=warm_client, model=MODEL, cache_dir=tmp_path, max_calls=10)
    warm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    # a brand new client with NO injected client and NO injected factory: if
    # this ever tried to build a real openai.OpenAI(), it would raise for
    # lack of an API key. It must not, because the cache is warm.
    cold = LLMClient(model=MODEL, cache_dir=tmp_path, max_calls=10)
    result = cold.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    assert result == SAMPLE_RESPONSE
    assert cold.calls_made == 0
    assert cold.cache_hits == 1


# --------------------------------------------------------------------------
# Transient-error retries (tenacity)
# --------------------------------------------------------------------------


def test_transient_error_is_retried_and_eventually_succeeds(tmp_path):
    fake_client = FakeOpenAIClient([transient_error(), valid_completion()])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    result = llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    assert result == SAMPLE_RESPONSE
    # per the module docstring: each actual HTTP attempt counts against budget
    assert llm.calls_made == 2
    assert len(fake_client.completions.calls) == 2


def test_transient_error_exhausts_retries_and_raises(tmp_path):
    fake_client = FakeOpenAIClient([transient_error(), transient_error(), transient_error()])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    with pytest.raises(openai.APIConnectionError):
        llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    assert llm.calls_made == 3  # 3 attempts, tenacity stop_after_attempt(3)


# --------------------------------------------------------------------------
# Request shape
# --------------------------------------------------------------------------


def test_request_uses_temperature_zero_and_strict_json_schema(tmp_path):
    fake_client = FakeOpenAIClient([valid_completion()])
    llm = LLMClient(client=fake_client, model=MODEL, cache_dir=tmp_path, max_calls=10)

    llm.complete_structured("plan_choice", SYSTEM, USER, RESPONSE_SCHEMA, SCHEMA_VERSION)

    call_kwargs = fake_client.completions.calls[0]
    assert call_kwargs["model"] == MODEL
    assert call_kwargs["temperature"] == 0
    assert call_kwargs["messages"][0] == {"role": "system", "content": SYSTEM}
    assert call_kwargs["messages"][1] == {"role": "user", "content": USER}

    response_format = call_kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"] == RESPONSE_SCHEMA
    assert response_format["json_schema"]["strict"] is True
