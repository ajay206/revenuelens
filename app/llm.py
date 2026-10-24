from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable


class LLM(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Generate a completion from system and user prompts."""
        raise NotImplementedError


class FakeLLM(LLM):
    """Fake LLM for testing that returns queued responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[str, str]] = []
        self._index = 0

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self._index < len(self.responses):
            resp = self.responses[self._index]
            self._index += 1
            return resp
        return "{}"


class OpenAICompatLLM(LLM):
    """OpenAI‑compatible API client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        extra: dict | None = None,
        *,
        timeout: float = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra = extra or {}
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            **self.extra,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "revenuelens",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("choices", [{}])[0].get("message", {}).get("content", "") or ""


class RetryingLLM(LLM):
    """Wraps another LLM and retries on transient HTTP errors."""

    def __init__(
        self,
        inner: LLM,
        *,
        name: str = "llm",
        tries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.inner = inner
        self.name = name
        self.tries = tries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.sleep = sleep

    def _should_retry(self, exc: Exception) -> bool:
        if isinstance(exc, urllib.error.HTTPError):
            return bool(exc.code == 429 or exc.code >= 500)
        return bool(isinstance(exc, (TimeoutError, urllib.error.URLError)))

    def _retry_delay(self, attempt: int, exc: urllib.error.HTTPError | None) -> float:
        if exc is not None and exc.headers:
            retry_after = exc.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                return min(int(retry_after), self.max_delay)
        # exponential back‑off
        return min(self.base_delay * (2 ** attempt), self.max_delay)

    def complete(self, system: str, user: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(self.tries):
            try:
                return self.inner.complete(system, user)
            except Exception as exc:
                if not self._should_retry(exc):
                    raise
                last_exc = exc
                if attempt == self.tries - 1:
                    break
                delay = self._retry_delay(attempt, exc if isinstance(exc, urllib.error.HTTPError) else None)
                self.sleep(delay)
        # All attempts exhausted
        assert last_exc is not None
        raise last_exc


class ChainLLM(LLM):
    """Tries a list of providers in order, returning the first non‑empty result."""

    def __init__(self, providers: list[tuple[str, LLM]]) -> None:
        self.providers = providers
        self.last_provider: str = "fallback"

    def complete(self, system: str, user: str) -> str:
        logger = logging.getLogger(__name__)
        for name, provider in self.providers:
            try:
                result = provider.complete(system, user)
                if result:
                    self.last_provider = name
                    return result
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM provider %s failed: %s", name, exc)
        self.last_provider = "fallback"
        return ""


def provider_chain_from_env(*, sleep: Callable[[float], None] = time.sleep) -> list[tuple[str, LLM]]:
    chain: list[tuple[str, LLM]] = []

    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        llm = OpenAICompatLLM(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            model="openai/gpt-oss-120b",
            extra={"reasoning_effort": "low"},
        )
        chain.append(("groq:openai/gpt-oss-120b", RetryingLLM(llm, name="groq", sleep=sleep)))

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        # poolside/laguna-s-2.1:free
        llm1 = OpenAICompatLLM(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_key,
            model="poolside/laguna-s-2.1:free",
        )
        chain.append(("openrouter:poolside/laguna-s-2.1:free", RetryingLLM(llm1, name="openrouter_poolside", sleep=sleep)))

        # nvidia/nemotron-3-ultra-550b-a55b:free
        llm2 = OpenAICompatLLM(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_key,
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
        )
        chain.append(("openrouter:nvidia/nemotron-3-ultra-550b-a55b:free", RetryingLLM(llm2, name="openrouter_nvidia", sleep=sleep)))

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        llm = OpenAICompatLLM(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key=gemini_key,
            model="gemini-3.1-flash-lite",
        )
        chain.append(("gemini:gemini-3.1-flash-lite", RetryingLLM(llm, name="gemini", sleep=sleep)))

    return chain


def free_llm_from_env() -> LLM:
    if os.getenv("RL_LLM") == "fake":
        return FakeLLM()

    providers = provider_chain_from_env()
    return ChainLLM(providers)


def parse_json(text: str) -> dict:
    """Parse JSON from text, handling markdown fences and partial JSON."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) > 1:
            stripped = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(stripped[first_brace : last_brace + 1])
        except json.JSONDecodeError:
            pass

    return {}
