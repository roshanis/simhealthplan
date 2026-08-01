"""LLM client infrastructure: a filesystem-cached, budget-capped wrapper
around the OpenAI Chat Completions structured-output API.

Design goals (see pipeline build spec — cost control: <=500 LLM calls for a
full county simulation):
  - **Cache-first, mandatory.** Every request is looked up in
    ``LLM_CACHE_DIR`` before any network call is considered. The cache key
    is a sha256 hash over a canonical JSON encoding of
    ``{model, system, user, schema_version}`` — changing the prompt, the
    model, or bumping ``schema_version`` all produce a new key. Cache files
    are plain, pretty-printed, human-readable JSON so they can be reviewed
    and committed to git by the orchestrator.
  - **Lazy client construction.** The real ``openai.OpenAI()`` client (which
    requires ``OPENAI_API_KEY`` to be set) is constructed lazily, only the
    first time a network call is actually needed. A run against a fully
    warm cache never constructs a client and never needs an API key.
  - **Budget ceiling.** ``MAX_LLM_CALLS`` bounds *network* calls only; cache
    hits are free. :class:`BudgetExceededError` is raised before a call that
    would exceed the budget — the rejected attempt never reaches the
    network and never increments ``calls_made``.
  - **Robustness.** Two independent retry layers exist:
      1. *Schema/parse failures* (the model returns content that isn't
         valid JSON, or refuses): one corrective retry is made with an
         appended corrective instruction. Both attempts count against the
         budget.
      2. *Transient transport/rate-limit errors*
         (``RateLimitError`` / ``APIConnectionError`` / ``APITimeoutError``
         / ``InternalServerError``) are retried via ``tenacity`` — 3
         attempts, exponential backoff.
    Budget accounting choice: rather than trying to distinguish "attempts
    that reached the API" from ones that didn't (OpenAI's SDK does not
    reliably expose that distinction to callers), every actual HTTP attempt
    — including each tenacity retry and each corrective retry — increments
    ``calls_made`` by exactly one. This is the simplest rule that can't
    silently blow through the ``MAX_LLM_CALLS`` ceiling.

Determinism note
-----------------
All requests use ``temperature=0`` and are cache-first, so a pipeline rerun
against a warm (committed) cache is byte-for-byte deterministic: no network
call and no ``OpenAI()`` construction ever happens. Regenerating the cache
(e.g. after a prompt or model change) can change an individual LLM
judgment, but downstream consumers blend many independent LLM outputs
(archetype-weighted counts, judge votes, etc.), so no single regenerated
response can flip the final backtest verdict.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import openai
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config.settings import settings

CALL_LOG_FILENAME = "call_log.jsonl"

_CORRECTIVE_INSTRUCTION = (
    "Your previous response could not be parsed as valid JSON conforming to "
    "the required schema. Respond again with ONLY a single JSON object that "
    "strictly matches the schema -- no prose, no markdown fences, no "
    "trailing commentary."
)

_SCHEMA_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


class BudgetExceededError(RuntimeError):
    """Raised when a network call would exceed ``MAX_LLM_CALLS`` for this run."""


class SchemaValidationError(RuntimeError):
    """Raised when the model's response cannot be parsed as the requested
    JSON schema even after one corrective retry."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cache_key(model: str, system: str, user: str, schema_version: str) -> str:
    """Sha256 hex digest over a canonical JSON encoding of the request identity.

    Canonical = sorted keys, no extraneous whitespace, so the same logical
    request always hashes to the same key regardless of dict ordering.
    """
    canonical = json.dumps(
        {"model": model, "system": system, "user": user, "schema_version": schema_version},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schema_name(prompt_key: str) -> str:
    """Sanitize ``prompt_key`` into a valid OpenAI json_schema ``name`` field."""
    name = _SCHEMA_NAME_RE.sub("_", prompt_key).strip("_")
    return (name or "response")[:64]


def _is_transient_openai_error(exc: BaseException) -> bool:
    transient_types = tuple(
        t
        for t in (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        )
        if t is not None
    )
    return isinstance(exc, transient_types)


def _retrying():
    """3 attempts, exponential backoff, transient OpenAI errors only."""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_transient_openai_error),
        reraise=True,
    )


class LLMClient:
    """Structured-output OpenAI client with a mandatory filesystem cache and
    a per-run call budget.

    Parameters
    ----------
    client:
        An already-constructed OpenAI-compatible client (``.chat.completions.create``).
        Intended for dependency injection in tests. When provided, no
        ``client_factory`` call is ever made.
    client_factory:
        A zero-arg callable that lazily builds the client on first network
        need. Defaults to ``openai.OpenAI``. Never invoked while the cache
        stays warm.
    model:
        Chat Completions model id. Defaults to ``settings.OPENAI_MODEL``.
    cache_dir:
        Directory holding ``<hash>.json`` cache files and ``call_log.jsonl``.
        Defaults to ``settings.LLM_CACHE_DIR``. Tests should always pass
        ``tmp_path`` here to avoid touching the real cache.
    max_calls:
        Network call budget. Defaults to ``settings.MAX_LLM_CALLS``.
    """

    def __init__(
        self,
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
        model: str | None = None,
        cache_dir: str | Path | None = None,
        max_calls: int | None = None,
    ) -> None:
        self._client = client
        self._client_factory = client_factory or openai.OpenAI
        self.model = model or settings.OPENAI_MODEL
        self.cache_dir = Path(cache_dir) if cache_dir is not None else settings.LLM_CACHE_DIR
        self.max_calls = settings.MAX_LLM_CALLS if max_calls is None else max_calls

        self.calls_made = 0
        self.cache_hits = 0

    # -- public API ---------------------------------------------------

    def complete_structured(
        self,
        prompt_key: str,
        system: str,
        user: str,
        response_schema: dict,
        schema_version: str,
    ) -> dict:
        """Return the parsed structured-output dict for this request.

        Cache-first: identical ``(model, system, user, schema_version)``
        always returns the same cached dict with zero network calls.
        """
        key = cache_key(self.model, system, user, schema_version)
        cache_path = self.cache_dir / f"{key}.json"

        cached = self._read_cache(cache_path)
        if cached is not None:
            self.cache_hits += 1
            return cached["response"]

        parsed, response_id = self._complete_with_corrective_retry(prompt_key, system, user, response_schema)
        self._write_cache(cache_path, prompt_key, schema_version, system, user, parsed, response_id)
        return parsed

    # -- client construction -------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    # -- request orchestration ------------------------------------------

    def _complete_with_corrective_retry(
        self, prompt_key: str, system: str, user: str, response_schema: dict
    ) -> tuple[dict, str | None]:
        parsed, response_id = self._attempt_and_parse(prompt_key, system, user, response_schema)
        if parsed is not None:
            return parsed, response_id

        corrective_user = f"{user}\n\n{_CORRECTIVE_INSTRUCTION}"
        parsed, response_id = self._attempt_and_parse(prompt_key, system, corrective_user, response_schema)
        if parsed is not None:
            return parsed, response_id

        raise SchemaValidationError(
            f"prompt_key={prompt_key!r}: model response was not valid JSON matching the "
            "requested schema, even after one corrective retry."
        )

    def _attempt_and_parse(
        self, prompt_key: str, system: str, user: str, response_schema: dict
    ) -> tuple[dict | None, str | None]:
        kwargs = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _schema_name(prompt_key),
                    "schema": response_schema,
                    "strict": True,
                },
            },
        }
        resp = self._budgeted_attempt(prompt_key, kwargs)

        message = resp.choices[0].message
        if getattr(message, "refusal", None):
            return None, None
        content = message.content
        if content is None:
            return None, None
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None, None
        return parsed, getattr(resp, "id", None)

    @_retrying()
    def _budgeted_attempt(self, prompt_key: str, kwargs: dict) -> Any:
        """Make exactly one HTTP attempt. Retried (by tenacity) on transient errors."""
        if self.calls_made >= self.max_calls:
            raise BudgetExceededError(
                f"LLM call budget exceeded: {self.calls_made}/{self.max_calls} calls already made "
                f"(prompt_key={prompt_key!r})"
            )
        client = self._ensure_client()
        self.calls_made += 1
        resp = client.chat.completions.create(**kwargs)
        self._append_call_log(prompt_key, kwargs["model"], resp)
        return resp

    # -- cache -----------------------------------------------------------

    @staticmethod
    def _read_cache(cache_path: Path) -> dict | None:
        if not cache_path.exists():
            return None
        return json.loads(cache_path.read_text())

    def _write_cache(
        self,
        cache_path: Path,
        prompt_key: str,
        schema_version: str,
        system: str,
        user: str,
        response: dict,
        response_id: str | None,
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "key": {
                "model": self.model,
                "prompt_key": prompt_key,
                "schema_version": schema_version,
            },
            "request": {"system": system, "user": user},
            "response": response,
            "response_id": response_id,
            "created_at": _now_iso(),
        }
        cache_path.write_text(json.dumps(payload, indent=2) + "\n")

    # -- call log ----------------------------------------------------------

    def _append_call_log(self, prompt_key: str, model: str, resp: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "ts": _now_iso(),
            "prompt_key": prompt_key,
            "model": model,
        }
        usage = getattr(resp, "usage", None)
        tokens = getattr(usage, "total_tokens", None) if usage is not None else None
        if tokens is not None:
            entry["tokens"] = tokens

        log_path = self.cache_dir / CALL_LOG_FILENAME
        with log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
