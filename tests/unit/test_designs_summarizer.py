"""Unit tests for services/designs/summarizer.py (D-16): the deterministic keyword
summary, the OpenAI chat summariser against httpx.MockTransport, and the env selection.
No network, no key."""
import asyncio
import json

import httpx
import pytest

from tests.unit.designs_testkit import load_designs

PROMPTS = ["vintage travel poster of Lisbon", "minimal forest sunset", "vintage sunset over the ocean"]
PURCHASES = ["Forest Mist (A3)", "Ocean Dawn (A2)"]


@pytest.fixture(scope="module")
def sm():
    return load_designs().summarizer


@pytest.fixture(scope="module")
def providers():
    return load_designs().providers


def _chat(sm, handler):
    return sm.OpenAIChatSummarizer(
        "sk-t", "gpt-4o-mini", base_url="https://api.openai.test/v1", transport=httpx.MockTransport(handler),
    )


def test_deterministic_summary_top_keywords(sm):
    assert sm.deterministic_summary(PROMPTS, PURCHASES) == (
        "You lean towards: vintage, forest, sunset, ocean, travel, lisbon."
    )


def test_deterministic_summary_empty(sm):
    assert sm.deterministic_summary([], []) == ""


def test_deterministic_summary_stopwords(sm):
    assert sm.deterministic_summary(["a poster with the style over from"], []) == ""


def test_deterministic_summarizer_class(sm):
    s = sm.DeterministicSummarizer()
    assert s.name == "deterministic"
    assert asyncio.run(s.summarize(PROMPTS, PURCHASES)) == sm.deterministic_summary(PROMPTS, PURCHASES)


def test_openai_chat_request_shape(sm):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "  You favour vintage travel scenes and soft sunsets.  "}}],
            "usage": {"total_tokens": 87},
        })

    s = _chat(sm, handler)
    assert s.name == "openai"
    out = asyncio.run(s.summarize(PROMPTS, PURCHASES))
    assert out == "You favour vintage travel scenes and soft sunsets."
    assert seen["path"] == "/v1/chat/completions"
    body = seen["body"]
    assert body["model"] == "gpt-4o-mini"
    assert body["max_completion_tokens"] == 120
    assert "temperature" not in body
    assert "max_tokens" not in body
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    assert "- vintage travel poster of Lisbon" in body["messages"][1]["content"]
    assert "- Forest Mist (A3)" in body["messages"][1]["content"]


def test_openai_chat_4xx_falls_back_to_deterministic(sm, providers):
    expected = sm.deterministic_summary(PROMPTS, PURCHASES)

    for status in (400, 401):
        def bad(request, status=status):
            return httpx.Response(status, json={"error": {"type": "invalid_request_error", "message": "nope"}})
        assert asyncio.run(_chat(sm, bad).summarize(PROMPTS, PURCHASES)) == expected

    for status in (429, 503):
        def down(request, status=status):
            return httpx.Response(status, json={"error": {"type": "rate_limit_error"}})
        with pytest.raises(providers.ProviderError):
            asyncio.run(_chat(sm, down).summarize(PROMPTS, PURCHASES))

    def network(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(providers.ProviderError):
        asyncio.run(_chat(sm, network).summarize(PROMPTS, PURCHASES))


def test_get_summarizer_selection(sm, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    assert isinstance(sm.get_summarizer(), sm.DeterministicSummarizer)

    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    s = sm.get_summarizer()
    assert isinstance(s, sm.OpenAIChatSummarizer)
    assert s.model == "gpt-4o-mini"

    monkeypatch.setenv("IMAGE_PROVIDER", "replicate")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(sm.get_summarizer(), sm.DeterministicSummarizer)
