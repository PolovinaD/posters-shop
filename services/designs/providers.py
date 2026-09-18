"""Pluggable image-generation providers (D-03) and the error taxonomy (D-05).

Selection mirrors notifications' EmailProvider/get_provider(): IMAGE_PROVIDER env
(fake | openai | replicate) -> get_image_provider(). FakeProvider is the compose
default and what the tests use: it paints a poster-shaped placeholder with Pillow
(title + wrapped prompt on a prompt-hash colour) and needs no key.

Error taxonomy (the worker and the circuit breaker classify on these names):

PromptRejected      - the vendor's safety filter refused the prompt: the generation
                      FAILS with a user-visible reason, no retry, never trips the breaker.
ProviderConfigError - a non-retryable 4xx (bad model, bad key): FAILS with a generic
                      reason, no retry, never trips the breaker (it is our
                      misconfiguration, not an outage).
ProviderError       - 429 / 5xx / network / timeout: RETRIED with backoff, trips the breaker.

FakeProvider test hooks (D-15): a prompt containing '[reject]' raises PromptRejected,
'[fail]' raises ProviderError, '[slow]' sleeps 3 s so the UI's generating state is demoable.
"""
import asyncio
import base64
import colorsys
import hashlib
import io
import os
import textwrap
from abc import ABC, abstractmethod

import httpx
from PIL import Image, ImageDraw, ImageFont

from logger import get_logger

logger = get_logger(__name__)

IMAGE_SIZE = "1024x1536"  # D-17: portrait 2:3, PNG
IMAGE_W, IMAGE_H = 1024, 1536

OPENAI_REFUSAL_REASON = "The provider's safety system rejected this prompt"


class ProviderError(Exception):
    """Transient provider failure (429 / 5xx / network / timeout): retry, trips the breaker."""


class PromptRejected(Exception):
    """The provider's safety filter refused the prompt: fail with a user-visible reason."""


class ProviderConfigError(Exception):
    """Non-retryable 4xx that is our misconfiguration (bad model, bad key): fail, no breaker trip."""


class ImageProvider(ABC):
    """Abstract image generator: prompt in, PNG bytes out."""

    name: str = "abstract"

    @abstractmethod
    async def generate(self, prompt: str, user_ref: str) -> bytes:
        """Return PNG bytes for the prompt. Raise PromptRejected / ProviderConfigError /
        ProviderError per the module docstring so the worker can classify the outcome."""
        raise NotImplementedError

    def params(self) -> dict:
        """Provider parameters recorded on the generation row."""
        return {"size": IMAGE_SIZE}


def user_ref(email: str) -> str:
    """Stable, non-reversible per-user reference forwarded to vendors (never the e-mail)."""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]


def paint_placeholder(prompt: str, w: int = IMAGE_W, h: int = IMAGE_H) -> bytes:
    """Paint a poster-shaped placeholder: title + wrapped prompt on a colour derived from
    the prompt hash (deterministic; always dark enough for white text)."""
    hue = hashlib.sha256(prompt.encode("utf-8")).digest()[0] / 255
    rgb = tuple(int(255 * c) for c in colorsys.hsv_to_rgb(hue, 0.55, 0.65))
    img = Image.new("RGB", (w, h), rgb)
    d = ImageDraw.Draw(img)
    d.text((64, 96), "AI POSTER", font=ImageFont.load_default(size=64), fill="white")
    body = ImageFont.load_default(size=40)
    y = 260
    for line in textwrap.wrap(prompt, width=34)[:14]:
        d.text((64, y), line, font=body, fill="white")
        y += 56
    d.rectangle([48, h - 140, w - 48, h - 64], outline="white", width=4)
    d.text(
        (64, h - 124), "PosterShop studio · placeholder render",
        font=ImageFont.load_default(size=28), fill="white",
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeProvider(ImageProvider):
    """Compose default and what the tests use. Hooks: '[reject]' -> PromptRejected,
    '[fail]' -> ProviderError, '[slow]' -> 3 s delay."""

    name = "fake"

    async def generate(self, prompt: str, user_ref: str) -> bytes:
        if "[reject]" in prompt:
            raise PromptRejected("The provider's safety filter rejected this prompt")
        if "[fail]" in prompt:
            raise ProviderError("fake provider: simulated transport failure")
        if "[slow]" in prompt:
            await asyncio.sleep(3)
        return paint_placeholder(prompt)


def classify_openai_error(r: httpx.Response) -> Exception:
    """Map an OpenAI error response to the taxonomy.

    Code/type FIRST, then status class (research pitfall 8): a wrong model is a 400
    too, and must never read as "your prompt was rejected" nor trip the breaker.
    """
    err = {}
    if r.headers.get("content-type", "").startswith("application/json"):
        try:
            err = (r.json() or {}).get("error") or {}
        except ValueError:
            err = {}
    code, typ = err.get("code"), err.get("type")
    msg = err.get("message") or r.text[:200]
    if code in ("moderation_blocked", "content_policy_violation") or typ == "image_generation_user_error":
        return PromptRejected(OPENAI_REFUSAL_REASON)
    if r.status_code == 429 or r.status_code >= 500:
        return ProviderError(f"openai {r.status_code}: {code or typ}: {msg}")
    return ProviderConfigError(f"openai {r.status_code}: {code or typ}: {msg}")


class OpenAIImagesProvider(ImageProvider):
    """OpenAI Images API (gpt-image models): one portrait PNG, returned as base64.

    The dall-e-only output-format selector is deliberately not sent (gpt-image rejects it).
    Timeouts raise httpx.TimeoutException (an HTTPError) -> ProviderError, so the
    worker retries and the breaker counts them.
    """

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        quality: str,
        base_url: str = "https://api.openai.com/v1",
        transport=None,
    ):
        self.model = model
        self.quality = quality
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(180.0, connect=10.0),
        )

    def params(self) -> dict:
        return {"size": IMAGE_SIZE, "model": self.model, "quality": self.quality, "output_format": "png"}

    async def generate(self, prompt: str, user_ref: str) -> bytes:
        body = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": IMAGE_SIZE,
            "quality": self.quality,
            "output_format": "png",
            "moderation": "auto",
            "user": user_ref,
        }
        try:
            r = await self._client.post("/images/generations", json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"openai transport: {e}") from e
        if r.status_code >= 400:
            raise classify_openai_error(r)
        data = r.json()
        usage = data.get("usage") or {}
        logger.info(
            "OpenAI image generated",
            model=self.model,
            quality=self.quality,
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        try:
            return base64.b64decode(data["data"][0]["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ProviderError(f"openai: unexpected response shape: {e}") from e


def get_image_provider() -> ImageProvider:
    """Select by IMAGE_PROVIDER (fake | openai | replicate).

    09-03 adds the real providers; until then anything but fake falls back to fake
    with a warning — never crash at startup (payments' init_provider philosophy).
    """
    wanted = os.getenv("IMAGE_PROVIDER", "fake").lower()
    if wanted != "fake":
        logger.warning("IMAGE_PROVIDER not available yet, falling back to fake", wanted=wanted)
    return FakeProvider()
