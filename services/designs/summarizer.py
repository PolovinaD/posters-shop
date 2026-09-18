"""Style-profile summariser (D-16): 1-2 sentences describing a customer's poster taste
from recent prompts + purchased poster names.

OpenAI chat (the same key as the image provider) when IMAGE_PROVIDER != fake AND a key
exists; otherwise a deterministic keyword summary so compose needs no key. 09-05 wires
the result into style_profiles.summary and prepends it to the prompt on "Personalise".

Error contract for the chat summariser: any 4xx degrades to the deterministic summary
(a bad chat model must never fail a generation); 429 / 5xx / network raise
ProviderError so the caller keeps the previous summary and tries again later.
"""
import os
import re
from abc import ABC, abstractmethod
from collections import Counter

import httpx

from logger import get_logger
from providers import ProviderError

logger = get_logger(__name__)

STOPWORDS = frozenset("""the and with over from that this into onto some very style image picture
    photo render illustration high quality detailed poster print design make create generate
    please want like would could should there their about after before under above between
    across through during without within colour color colours colors background foreground""".split())
TOKEN_RE = re.compile(r"[a-zA-Z]{4,}")
SYSTEM_PROMPT = (
    "You write one or two sentences describing a customer's poster taste in the second person. "
    "No preamble, no lists."
)


class Summarizer(ABC):
    """Abstract summariser: prompts + purchase names in, 1-2 sentences out."""

    name: str = "abstract"

    @abstractmethod
    async def summarize(self, prompts: list[str], purchases: list[str]) -> str:
        raise NotImplementedError


class DeterministicSummarizer(Summarizer):
    """Key-free fallback: the top keywords by frequency (compose default, tests)."""

    name = "deterministic"

    async def summarize(self, prompts: list[str], purchases: list[str]) -> str:
        return deterministic_summary(prompts, purchases)


class OpenAIChatSummarizer(Summarizer):
    """Chat Completions summary. Uses max_completion_tokens (never the legacy limit
    field) and omits the sampling temperature so a gpt-5-family override works too."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        transport=None,
    ):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def summarize(self, prompts: list[str], purchases: list[str]) -> str:
        user = (
            "Recent prompts:\n- " + "\n- ".join(prompts or ["(none)"])
            + "\n\nPurchased posters:\n- " + "\n- ".join(purchases or ["(none)"])
        )
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": 120,
        }
        try:
            r = await self._client.post("/chat/completions", json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"openai chat transport: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise ProviderError(f"openai chat {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            logger.warning(
                "OpenAI chat rejected the summary request; using the deterministic summary",
                status=r.status_code, body=r.text[:200],
            )
            return deterministic_summary(prompts, purchases)
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, ValueError):
            return deterministic_summary(prompts, purchases)
        usage = data.get("usage") or {}
        logger.info("Style summary generated", model=self.model, total_tokens=usage.get("total_tokens"))
        return text or deterministic_summary(prompts, purchases)


def deterministic_summary(prompts: list[str], purchases: list[str], top: int = 6) -> str:
    """Top-`top` tokens (>= 4 letters, lower-cased, stopwords removed) ranked by frequency
    desc, then first appearance across prompts + purchases."""
    counts = Counter()
    first = {}
    for i, text in enumerate([*prompts, *purchases]):
        for tok in TOKEN_RE.findall(text):
            t = tok.lower()
            if t in STOPWORDS:
                continue
            counts[t] += 1
            first.setdefault(t, (i, len(first)))
    if not counts:
        return ""
    ranked = sorted(counts, key=lambda t: (-counts[t], first[t]))[:top]
    return "You lean towards: " + ", ".join(ranked) + "."


def get_summarizer() -> Summarizer:
    """D-16: fake mode OR no key -> deterministic; otherwise OpenAI chat with the same key."""
    provider = os.getenv("IMAGE_PROVIDER", "fake").strip().lower()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if provider == "fake" or not key:
        return DeterministicSummarizer()
    return OpenAIChatSummarizer(
        key,
        os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
