"""Unit tests for services/designs/providers.py: the fake provider, the placeholder
painter, the error taxonomy and the env-driven provider selection. No network, no key."""
import asyncio
import hashlib
import io

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
