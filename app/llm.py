"""LLM integration for RevenueLens."""

from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod


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
    """OpenAI-compatible API client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        extra: dict | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra = extra or {}

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
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("choices", [{}])[0].get("message", {}).get("content", "") or ""


def free_llm_from_env() -> LLM:
    """Create an LLM instance based on environment variables."""
    if os.environ.get("RL_LLM") == "fake":
        return FakeLLM()

    if groq_key := os.environ.get("GROQ_API_KEY"):
        return OpenAICompatLLM(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            model="openai/gpt-oss-120b",
            extra={"reasoning_effort": "low"},
        )

    if openrouter_key := os.environ.get("OPENROUTER_API_KEY"):
        return OpenAICompatLLM(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_key,
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
        )

    if gemini_key := os.environ.get("GEMINI_API_KEY"):
        return OpenAICompatLLM(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key=gemini_key,
            model="gemini-3.1-flash-lite",
        )

    return FakeLLM()


def parse_json(text: str) -> dict:
    """Parse JSON from text, handling markdown fences and partial JSON."""
    stripped = text.strip()
    # Remove markdown code fences
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) > 1:
            stripped = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON object from text
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(stripped[first_brace : last_brace + 1])
        except json.JSONDecodeError:
            pass

    return {}
