"""Unit tests for services/designs/providers.py: the fake provider, the placeholder
painter, the error taxonomy and the env-driven provider selection. No network, no key."""
import asyncio
import base64
import hashlib
import io
import json

import httpx
import pytest
from PIL import Image

from tests.unit.designs_testkit import load_designs

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def providers():
    return load_designs().providers


def test_paint_placeholder_is_portrait_png(providers):
    png = providers.paint_placeholder("a lighthouse at dusk")
    assert png[:8] == PNG_SIGNATURE
    img = Image.open(io.BytesIO(png))
    assert img.size == (1024, 1536)
    assert img.mode == "RGB"


def test_paint_placeholder_colour_is_deterministic(providers):
    assert providers.paint_placeholder("sunset") == providers.paint_placeholder("sunset")
    sunset = Image.open(io.BytesIO(providers.paint_placeholder("sunset"))).getpixel((10, 10))
    forest = Image.open(io.BytesIO(providers.paint_placeholder("forest"))).getpixel((10, 10))
    assert sunset != forest


def test_fake_generate_returns_png(providers):
    fake = providers.FakeProvider()
    png = asyncio.run(fake.generate("a poster", "u1"))
    assert png[:8] == PNG_SIGNATURE
    assert fake.name == "fake"
    assert fake.params() == {"size": "1024x1536"}


def test_fake_reject_hook(providers):
    with pytest.raises(providers.PromptRejected) as exc:
        asyncio.run(providers.FakeProvider().generate("cats [reject]", "u1"))
    assert "rejected" in str(exc.value)


def test_fake_fail_hook(providers):
    with pytest.raises(providers.ProviderError):
        asyncio.run(providers.FakeProvider().generate("cats [fail]", "u1"))


def test_error_taxonomy_is_distinct(providers):
    classes = (providers.PromptRejected, providers.ProviderConfigError, providers.ProviderError)
    for cls in classes:
        assert issubclass(cls, Exception)
    for a in classes:
        for b in classes:
            if a is not b:
                assert not issubclass(a, b), f"{a.__name__} must not subclass {b.__name__}"


def test_get_image_provider_defaults_to_fake(providers, monkeypatch):
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    assert isinstance(providers.get_image_provider(), providers.FakeProvider)
    monkeypatch.setenv("IMAGE_PROVIDER", "nonsense")
    assert isinstance(providers.get_image_provider(), providers.FakeProvider)


def test_user_ref_is_stable_hash(providers):
    assert providers.user_ref("a@b.c") == hashlib.sha256(b"a@b.c").hexdigest()[:32]


# ============== OpenAIImagesProvider (09-03, httpx.MockTransport only) ==============

def _png_b64(providers):
    # 128x192: the smallest canvas the footer rectangle (x0=48, x1=w-48) fits on
    return base64.b64encode(providers.paint_placeholder("x", 128, 192)).decode()


def _openai(providers, handler):
    return providers.OpenAIImagesProvider(
        api_key="sk-test", model="gpt-image-1.5", quality="medium",
        base_url="https://api.openai.test/v1", transport=httpx.MockTransport(handler),
    )


def _openai_error(status, error, headers=None):
    def handler(request):
        return httpx.Response(status, json={"error": error}, headers=headers)
    return handler


def test_openai_request_shape_and_decode(providers):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "created": 1, "data": [{"b64_json": _png_b64(providers)}], "usage": {"output_tokens": 1584},
        })

    provider = _openai(providers, handler)
    png = asyncio.run(provider.generate("a poster", "u1"))
    assert png[:8] == PNG_SIGNATURE
    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/images/generations"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"] == {
        "model": "gpt-image-1.5", "prompt": "a poster", "n": 1, "size": "1024x1536",
        "quality": "medium", "output_format": "png", "moderation": "auto", "user": "u1",
    }
    assert provider.name == "openai"
    assert provider.params() == {
        "size": "1024x1536", "model": "gpt-image-1.5", "quality": "medium", "output_format": "png",
    }


def test_openai_moderation_blocked_is_prompt_rejected(providers):
    handler = _openai_error(400, {
        "type": "image_generation_user_error", "code": "moderation_blocked", "message": "Your request was rejected",
    })
    with pytest.raises(providers.PromptRejected) as exc:
        asyncio.run(_openai(providers, handler).generate("a poster", "u1"))
    assert str(exc.value) == "The provider's safety system rejected this prompt"


def test_openai_legacy_content_policy_is_prompt_rejected(providers):
    handler = _openai_error(400, {
        "type": "invalid_request_error", "code": "content_policy_violation", "message": "rejected",
    })
    with pytest.raises(providers.PromptRejected):
        asyncio.run(_openai(providers, handler).generate("a poster", "u1"))


def test_openai_other_400_is_config_error(providers):
    handler = _openai_error(400, {"type": "invalid_request_error", "code": None, "message": "Invalid model"})
    with pytest.raises(providers.ProviderConfigError) as exc:
        asyncio.run(_openai(providers, handler).generate("a poster", "u1"))
    assert "400" in str(exc.value)
    assert "Invalid model" in str(exc.value)

    handler = _openai_error(401, {"type": "invalid_request_error", "code": "invalid_api_key"})
    with pytest.raises(providers.ProviderConfigError):
        asyncio.run(_openai(providers, handler).generate("a poster", "u1"))


def test_openai_429_and_5xx_are_provider_errors(providers):
    handler = _openai_error(429, {"type": "rate_limit_error", "code": None})
    with pytest.raises(providers.ProviderError):
        asyncio.run(_openai(providers, handler).generate("a poster", "u1"))

    handler = _openai_error(429, {"code": "insufficient_quota"})
    with pytest.raises(providers.ProviderError):
        asyncio.run(_openai(providers, handler).generate("a poster", "u1"))

    def html_502(request):
        return httpx.Response(502, text="<html><body>Bad gateway</body></html>",
                              headers={"content-type": "text/html"})

    with pytest.raises(providers.ProviderError):
        asyncio.run(_openai(providers, html_502).generate("a poster", "u1"))


def test_openai_network_error_is_provider_error(providers):
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(providers.ProviderError):
        asyncio.run(_openai(providers, handler).generate("a poster", "u1"))


def test_classify_openai_error_direct(providers):
    req = httpx.Request("POST", "https://x/y")
    refusal = providers.classify_openai_error(
        httpx.Response(400, json={"error": {"code": "moderation_blocked"}}, request=req)
    )
    assert isinstance(refusal, providers.PromptRejected)
    outage = providers.classify_openai_error(
        httpx.Response(503, text="upstream down", headers={"content-type": "text/plain"}, request=req)
    )
    assert isinstance(outage, providers.ProviderError)
    config = providers.classify_openai_error(
        httpx.Response(404, json={"error": {"type": "invalid_request_error", "code": "model_not_found"}}, request=req)
    )
    assert isinstance(config, providers.ProviderConfigError)


# ============== ReplicateProvider (09-03, httpx.MockTransport only, no token — D-10) ==============

CREATE_PATH = "/v1/models/black-forest-labs/flux-schnell/predictions"
OUTPUT_URL = "https://replicate.delivery.test/out.png"


def _replicate(providers, handler, deadline=5.0):
    return providers.ReplicateProvider(
        token="r8_test", model="black-forest-labs/flux-schnell",
        base_url="https://api.replicate.test/v1", transport=httpx.MockTransport(handler),
        poll_interval=0.0, deadline=deadline,
    )


def _png(providers):
    return providers.paint_placeholder("x", 128, 192)


def test_replicate_create_wait_succeeded_downloads_output(providers):
    seen = {}
    png = _png(providers)

    def handler(request):
        if request.url.path == CREATE_PATH:
            seen["prefer"] = request.headers["prefer"]
            seen["auth"] = request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": "p1", "status": "succeeded", "output": [OUTPUT_URL]})
        if request.url.host == "replicate.delivery.test" and request.url.path == "/out.png":
            return httpx.Response(200, content=png, headers={"content-type": "image/png"})
        return httpx.Response(500, text="unexpected " + str(request.url))

    provider = _replicate(providers, handler)
    assert asyncio.run(provider.generate("a poster", "u1")) == png
    assert seen["prefer"] == "wait=60"
    assert seen["auth"] == "Bearer r8_test"
    assert seen["body"] == {"input": {
        "prompt": "a poster", "aspect_ratio": "2:3", "output_format": "png",
        "output_quality": 90, "num_outputs": 1, "megapixels": "1",
    }}
    assert provider.name == "replicate"
    assert provider.params() == {
        "size": "2:3@1MP", "model": "black-forest-labs/flux-schnell", "aspect_ratio": "2:3", "megapixels": "1",
    }


def test_replicate_output_as_plain_string_is_downloaded(providers):
    """flux-1.1-pro returns `output` as one URL string, not a list (live, 2026-09-20)."""
    png = _png(providers)

    def handler(request):
        if request.url.path == CREATE_PATH:
            return httpx.Response(201, json={"id": "p1", "status": "succeeded", "output": OUTPUT_URL})
        if request.url.host == "replicate.delivery.test" and request.url.path == "/out.png":
            return httpx.Response(200, content=png, headers={"content-type": "image/png"})
        return httpx.Response(500, text="unexpected " + str(request.url))

    assert asyncio.run(_replicate(providers, handler).generate("a poster", "u1")) == png


def test_replicate_empty_output_is_provider_error(providers):
    def handler(request):
        return httpx.Response(201, json={"id": "p1", "status": "succeeded", "output": []})

    with pytest.raises(providers.ProviderError, match="no output URL"):
        asyncio.run(_replicate(providers, handler).generate("a poster", "u1"))


def test_replicate_polls_until_succeeded(providers):
    polls = {"n": 0}
    png = _png(providers)

    def handler(request):
        if request.url.path == CREATE_PATH:
            return httpx.Response(201, json={"id": "p1", "status": "starting", "output": None})
        if request.url.path == "/v1/predictions/p1":
            polls["n"] += 1
            if polls["n"] == 1:
                return httpx.Response(200, json={"id": "p1", "status": "processing", "output": None})
            return httpx.Response(200, json={"id": "p1", "status": "succeeded", "output": [OUTPUT_URL]})
        if request.url.path == "/out.png":
            return httpx.Response(200, content=png)
        return httpx.Response(500, text="unexpected " + str(request.url))

    assert asyncio.run(_replicate(providers, handler).generate("a poster", "u1")) == png
    assert polls["n"] == 2


def test_replicate_nsfw_is_prompt_rejected(providers):
    def handler(request):
        return httpx.Response(201, json={"id": "p1", "status": "failed", "error": "NSFW content detected"})

    with pytest.raises(providers.PromptRejected) as exc:
        asyncio.run(_replicate(providers, handler).generate("a poster", "u1"))
    assert str(exc.value) == "The provider's safety checker rejected this prompt"


def test_replicate_failed_other_is_provider_error(providers):
    def oom(request):
        return httpx.Response(201, json={"id": "p1", "status": "failed", "error": "CUDA out of memory"})

    with pytest.raises(providers.ProviderError):
        asyncio.run(_replicate(providers, oom).generate("a poster", "u1"))

    def canceled(request):
        return httpx.Response(201, json={"id": "p1", "status": "canceled", "error": None})

    with pytest.raises(providers.ProviderError):
        asyncio.run(_replicate(providers, canceled).generate("a poster", "u1"))


def test_replicate_deadline_is_provider_error(providers):
    def handler(request):
        if request.url.path == CREATE_PATH:
            return httpx.Response(201, json={"id": "p1", "status": "starting"})
        return httpx.Response(200, json={"id": "p1", "status": "processing"})

    with pytest.raises(providers.ProviderError) as exc:
        asyncio.run(_replicate(providers, handler, deadline=0.0).generate("a poster", "u1"))
    assert "deadline" in str(exc.value)


def test_replicate_http_errors(providers):
    def create_status(status, body):
        def handler(request):
            if request.url.path == CREATE_PATH:
                return httpx.Response(status, json=body)
            return httpx.Response(500, text="unexpected")
        return handler

    throttled = create_status(429, {"detail": "Request was throttled. Expected available in 3 seconds."})
    with pytest.raises(providers.ProviderError):
        asyncio.run(_replicate(providers, throttled).generate("a poster", "u1"))

    with pytest.raises(providers.ProviderConfigError):
        asyncio.run(_replicate(providers, create_status(401, {"detail": "Unauthenticated"})).generate("a poster", "u1"))

    with pytest.raises(providers.ProviderConfigError):
        asyncio.run(_replicate(providers, create_status(422, {"detail": "bad input"})).generate("a poster", "u1"))

    with pytest.raises(providers.ProviderError):
        asyncio.run(_replicate(providers, create_status(500, {"detail": "boom"})).generate("a poster", "u1"))

    def download_404(request):
        if request.url.path == CREATE_PATH:
            return httpx.Response(201, json={"id": "p1", "status": "succeeded", "output": [OUTPUT_URL]})
        return httpx.Response(404, text="gone")

    with pytest.raises(providers.ProviderError):
        asyncio.run(_replicate(providers, download_404).generate("a poster", "u1"))


# ============== get_image_provider env switch (09-03) ==============

def _clear_provider_env(monkeypatch):
    for var in (
        "IMAGE_PROVIDER", "OPENAI_API_KEY", "OPENAI_IMAGE_MODEL", "OPENAI_IMAGE_QUALITY", "OPENAI_BASE_URL",
        "REPLICATE_API_TOKEN", "REPLICATE_MODEL", "REPLICATE_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_get_image_provider_openai_with_key(providers, monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-flare")
    monkeypatch.setenv("OPENAI_IMAGE_QUALITY", "low")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.test/v1")
    p = providers.get_image_provider()
    assert isinstance(p, providers.OpenAIImagesProvider)
    assert p.model == "gpt-image-2.5-flare"
    assert p.quality == "low"
    assert str(p._client.base_url).startswith("https://proxy.test/v1")


def test_get_image_provider_openai_without_key_falls_back(providers, monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    assert isinstance(providers.get_image_provider(), providers.FakeProvider)


def test_get_image_provider_replicate(providers, monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "replicate")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_x")
    monkeypatch.setenv("REPLICATE_MODEL", "owner/name")
    p = providers.get_image_provider()
    assert isinstance(p, providers.ReplicateProvider)
    assert p.model == "owner/name"

    monkeypatch.delenv("REPLICATE_API_TOKEN")
    assert isinstance(providers.get_image_provider(), providers.FakeProvider)


def test_get_image_provider_defaults(providers, monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "OpenAI")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    p = providers.get_image_provider()
    assert isinstance(p, providers.OpenAIImagesProvider)
    assert p.model == "gpt-image-1.5"
    assert p.quality == "medium"
    assert str(p._client.base_url).startswith("https://api.openai.com/v1")
