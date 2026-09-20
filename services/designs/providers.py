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
import time
from abc import ABC, abstractmethod

import httpx
from PIL import Image, ImageDraw, ImageFont

from logger import get_logger

logger = get_logger(__name__)

IMAGE_SIZE = "1024x1536"  # D-17: portrait 2:3, PNG
IMAGE_W, IMAGE_H = 1024, 1536

OPENAI_REFUSAL_REASON = "The provider's safety system rejected this prompt"
REPLICATE_REFUSAL_REASON = "The provider's safety checker rejected this prompt"


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


class ReplicateProvider(ImageProvider):
    """Serverless GPU provider (create prediction -> poll -> download).

    Built and mocked only (no token yet, D-10); shares the seam with OpenAI so the
    thesis comparison is honest. `Prefer: wait=60` holds the create call until the
    prediction finishes (flux-schnell usually does within seconds), otherwise the
    loop polls every `poll_interval` s up to `deadline` s. Outputs on
    replicate.delivery vanish after ~1 h (research pitfall 9), so the bytes are
    downloaded inside the same attempt and never the URL stored.
    """

    name = "replicate"

    def __init__(
        self,
        token: str,
        model: str = "black-forest-labs/flux-schnell",
        base_url: str = "https://api.replicate.com/v1",
        transport=None,
        poll_interval: float = 2.0,
        deadline: float = 180.0,
    ):
        self.model = model
        self.poll_interval = poll_interval
        self.deadline = deadline
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(90.0, connect=10.0),
        )

    def params(self) -> dict:
        return {"size": "2:3@1MP", "model": self.model, "aspect_ratio": "2:3", "megapixels": "1"}

    async def generate(self, prompt: str, user_ref: str) -> bytes:
        body = {"input": {
            "prompt": prompt,
            "aspect_ratio": "2:3",
            "output_format": "png",
            "output_quality": 90,
            "num_outputs": 1,
            "megapixels": "1",
        }}
        try:
            r = await self._client.post(
                f"/models/{self.model}/predictions", headers={"Prefer": "wait=60"}, json=body,
            )
            if r.status_code == 429 or r.status_code >= 500:
                raise ProviderError(f"replicate {r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:
                raise ProviderConfigError(f"replicate {r.status_code}: {r.text[:200]}")
            pred = r.json()
            started = time.monotonic()
            while pred.get("status") in ("starting", "processing"):
                if time.monotonic() - started > self.deadline:
                    raise ProviderError("replicate: poll deadline exceeded")
                await asyncio.sleep(self.poll_interval)
                pr = await self._client.get(f"/predictions/{pred['id']}")
                if pr.status_code >= 400:
                    raise ProviderError(f"replicate poll {pr.status_code}")
                pred = pr.json()
            if pred.get("status") != "succeeded":
                err = str(pred.get("error") or pred.get("status"))
                if "nsfw" in err.lower():
                    raise PromptRejected(REPLICATE_REFUSAL_REASON)
                raise ProviderError(f"replicate: {err}")
            # `output` is a list of URLs for flux-schnell but a single URL string for
            # flux-1.1-pro (seen live 2026-09-20: `[0]` on the string took the letter
            # "h" and the download 404ed). Accept both.
            out = pred.get("output")
            url = out[0] if isinstance(out, list) and out else out if isinstance(out, str) else None
            if not url:
                raise ProviderError("replicate: no output URL")
            # An absolute URL overrides base_url; download NOW (replicate.delivery expires in ~1 h).
            img = await self._client.get(url)
            if img.status_code >= 400:
                raise ProviderError(f"replicate download {img.status_code}")
            logger.info(
                "Replicate image generated",
                model=self.model,
                predict_time=(pred.get("metrics") or {}).get("predict_time"),
            )
            return img.content
        except httpx.HTTPError as e:
            raise ProviderError(f"replicate transport: {e}") from e


def get_image_provider() -> ImageProvider:
    """IMAGE_PROVIDER = fake | openai | replicate (D-03).

    A real provider without its key falls back to fake with a warning so the service
    always starts (payments' init_provider philosophy); the API keeps accepting jobs.
    """
    wanted = os.getenv("IMAGE_PROVIDER", "fake").strip().lower()
    if wanted == "openai":
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if key:
            return OpenAIImagesProvider(
                key,
                os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5"),
                os.getenv("OPENAI_IMAGE_QUALITY", "medium"),
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            )
        logger.warning("IMAGE_PROVIDER=openai but OPENAI_API_KEY is empty; falling back to the fake provider")
    elif wanted == "replicate":
        token = os.getenv("REPLICATE_API_TOKEN", "").strip()
        if token:
            return ReplicateProvider(
                token,
                os.getenv("REPLICATE_MODEL", "black-forest-labs/flux-schnell"),
                base_url=os.getenv("REPLICATE_BASE_URL", "https://api.replicate.com/v1"),
            )
        logger.warning("IMAGE_PROVIDER=replicate but REPLICATE_API_TOKEN is empty; falling back to the fake provider")
    elif wanted != "fake":
        logger.warning("Unknown IMAGE_PROVIDER; falling back to the fake provider", wanted=wanted)
    return FakeProvider()
