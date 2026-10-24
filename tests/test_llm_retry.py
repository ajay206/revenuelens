import urllib.error
import urllib.request
from collections import deque
from email.message import Message

import pytest

from app.currency import fix_currency
from app.explain import explain_finding
from app.llm import LLM, ChainLLM, FakeLLM, RetryingLLM
from app.reconcile import Finding


class StubLLM(LLM):
    def __init__(self, responses: list[str] | None = None, side_effect: Exception | None = None, once: bool = False):
        self.responses = deque(responses or [])
        self.side_effect = side_effect
        self.once = once
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.side_effect:
            exc = self.side_effect
            if self.once:
                self.side_effect = None
            raise exc
        return self.responses.popleft() if self.responses else ""


def test_retrying_llm_429_retry_after():
    recorded = []
    headers = Message()
    headers.add_header("Retry-After", "2")
    # First call fails, second succeeds
    inner = StubLLM(
        responses=['{"title":"t"}'],
        side_effect=urllib.error.HTTPError("url", 429, "Too Many", headers, None),
        once=True,
    )

    def sleep_mock(secs):
        recorded.append(int(secs))

    retry = RetryingLLM(inner, sleep=sleep_mock)
    resp = retry.complete("sys", "user")

    assert resp == '{"title":"t"}'
    assert recorded == [2]


def test_retrying_llm_503_exhaust_retries():
    recorded = []
    inner = StubLLM(
        side_effect=urllib.error.HTTPError("url", 503, "Service Unavailable", Message(), None)
    )

    def sleep_mock(secs):
        recorded.append(int(secs))

    retry = RetryingLLM(inner, sleep=sleep_mock)
    with pytest.raises(urllib.error.HTTPError):
        retry.complete("sys", "user")

    assert len(recorded) == 2  # 3 tries total = 2 sleeps


def test_retrying_llm_400_no_retry():
    inner = StubLLM(
        side_effect=urllib.error.HTTPError("url", 400, "Bad Request", Message(), None)
    )
    retry = RetryingLLM(inner)
    with pytest.raises(urllib.error.HTTPError):
        retry.complete("sys", "user")


def test_chain_llm_fallback():
    # Setup 3 providers, 2 fail, 3rd succeeds
    fail1 = RetryingLLM(StubLLM(side_effect=urllib.error.HTTPError("u", 500, "", Message(), None)))
    fail2 = RetryingLLM(StubLLM(side_effect=TimeoutError()))
    success = RetryingLLM(StubLLM(responses=['{"title":"success"}']))

    chain = ChainLLM([("p1", fail1), ("p2", fail2), ("p3", success)])
    resp = chain.complete("s", "u")

    assert resp == '{"title":"success"}'
    assert chain.last_provider == "p3"

    # All fail
    chain = ChainLLM([("p1", fail1), ("p2", fail2)])
    resp = chain.complete("s", "u")
    assert resp == ""
    assert chain.last_provider == "fallback"


def test_explain_finding_fallback():
    # Chain that always fails
    chain = ChainLLM([("p1", RetryingLLM(StubLLM(side_effect=ValueError("boom"))))])
    finding = Finding(
        check="unrated_usage",
        record_ids=["1"],
        table="USG_CDR",
        customer_id="C1",
        period="202608",
        impact=-120.5,
        evidence={},
        description="d",
    )

    story = explain_finding(finding, [], llm=chain)
    assert story.money_impact == 120.50
    assert story.title != ""  # Should be the fallback story


def test_currency_and_fake_llm_integration(monkeypatch):
    monkeypatch.delenv("RL_CURRENCY", raising=False)
    fake = FakeLLM(
        responses=[
            '{"title":"Lost $120.50","what":"Customer billed USD 120.50 less","since_when":"202608","root_cause":"x","who_affected":"y","what_to_do":"z"}'
        ]
    )
    # Mocking explain_finding dependency internally to test result
    finding = Finding(
        check="unrated_usage",
        record_ids=["1"],
        table="USG_CDR",
        customer_id="C1",
        period="202608",
        impact=-120.5,
        evidence={},
        description="d",
    )

    story = explain_finding(finding, [], llm=fake)
    assert "₹120.50" in story.title
    assert "₹120.50" in story.what
    assert "$" not in story.title
    assert "₹" in fake.calls[0][0]  # System prompt
    assert "INR" in fake.calls[0][0]


def test_fix_currency_units():
    assert fix_currency("$100", "INR", "₹") == "₹100"
    assert fix_currency("USD 100", "INR", "₹") == "₹100"
    assert fix_currency("Rs. 100", "INR", "₹") == "₹100"
    assert fix_currency("Rs 100", "INR", "₹") == "₹100"
    assert fix_currency("₹100", "USD", "$") == "$100"
    assert fix_currency("Rs. 100", "USD", "$") == "$100"
    assert fix_currency("Price is 100", "INR", "₹") == "Price is 100"


def test_cached_llm_without_db(monkeypatch):
    # Simulate bad DB config
    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid@127.0.0.1:1/x")
    from app.llm_cache import CachedLLM

    inner = StubLLM(responses=['{"ok":"yes"}'])
    cached = CachedLLM(inner)
    resp = cached.complete("s", "u")
    assert resp == '{"ok":"yes"}'
