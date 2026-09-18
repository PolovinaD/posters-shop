"""Print-this (D-06/D-11/D-12, 09-04): the SKU scheme, the seed price ladder, the
catalog-then-inventory orchestration and the route's status mapping.

printing.py is exercised with fake clients (no HTTP, no breaker); the route with
TestClient + dependency overrides (test_designs_api.py pattern) and the two client
functions monkeypatched with AsyncMocks, so a downstream refusal/outage/open breaker
is simulated exactly where the route catches it."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from tests.unit.designs_testkit import load_designs

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
CLAIMS = {"sub": "c@x.io", "role": "customer"}
KEY = "k" * 32 + ".png"
IMAGE_URL = f"/api/designs/images/{KEY}"
LONG_PROMPT = "  A very   long prompt " + "x" * 80
EXPECTED_PAYLOAD = {
    "sku": "AI-7",
    "name": "Custom: A very long prompt " + "x" * 41,  # 19 chars of words + 41 x = the 60-char cap
    "description": LONG_PROMPT.strip(),
    "category": "Custom",
    "image_url": IMAGE_URL,
    "listed": False,
    "active": True,
    "variants": [
        {"size": "A4", "price": "24.99"},
        {"size": "A3", "price": "29.99"},
        {"size": "A2", "price": "39.99"},
        {"size": "A1", "price": "54.99"},
    ],
}


@pytest.fixture(scope="module")
def d():
    return load_designs()


@pytest.fixture(scope="module")
def pr(d):
    return d.printing


@pytest.fixture(scope="module")
def main(d):
    return d.main


@pytest.fixture(scope="module")
def client(main):
    return TestClient(main.app)


def _gen(**over):
    base = dict(
        id=7, customer_email="c@x.io", prompt=LONG_PROMPT, effective_prompt=LONG_PROMPT, personalise=False,
        provider="fake", status="ready", failure_reason=None, image_key=KEY, attempts=1,
        retry_after=None, created_at=NOW, started_at=NOW, finished_at=NOW, purchased_at=None,
        catalog_product_sku=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


class FakeCatalog:
    def __init__(self, log, fail=None):
        self.calls, self.log, self.fail = [], log, fail

    async def create_product_family(self, payload):
        self.calls.append(payload)
        self.log.append("catalog")
        if self.fail:
            raise self.fail
        return {"sku": payload["sku"], "listed": payload["listed"],
                "variants": [{"sku": f"{payload['sku']}-{v['size']}"} for v in payload["variants"]]}


class FakeInventory:
    def __init__(self, log, fail=None):
        self.calls, self.log, self.fail = [], log, fail

    async def create_stock(self, items):
        self.calls.append(items)
        self.log.append("inventory")
        if self.fail:
            raise self.fail
        return {"created": [i["sku"] for i in items], "skipped": []}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_sku_scheme(pr):
    assert pr.motif_sku(7) == "AI-7"
    assert pr.variant_sku(7, "A3") == "AI-7-A3"
    assert pr.generation_id_from_sku("AI-7-A3") == 7
    assert pr.generation_id_from_sku("AI-123-A1") == 123
    assert pr.generation_id_from_sku("AI-7") is None          # the motif is not sellable
    assert pr.generation_id_from_sku("POSTER-001-A3") is None  # an ordinary poster
    assert pr.generation_id_from_sku("AI-7-A5") is None        # not a catalog format
    assert pr.generation_id_from_sku("ai-7-a3") is None        # case matters
    assert pr.generation_id_from_sku("") is None and pr.generation_id_from_sku(None) is None
    assert pr.SIZES == ["A4", "A3", "A2", "A1"]


def test_product_name_trims_and_caps(pr):
    name = pr.product_name(LONG_PROMPT)
    assert name == "Custom: " + " ".join(LONG_PROMPT.split())[:60]
    assert name.startswith("Custom: A very long prompt x")
    assert len(name) <= 68
    assert pr.product_name("short") == "Custom: short"


def test_ladder_from_base_price(pr):
    payload = pr.build_product_payload(_gen(), image_url=IMAGE_URL, base_price=Decimal("29.99"))
    assert payload == EXPECTED_PAYLOAD
    # the ladder is the catalog seed's: -5 / 0 / +10 / +25 from one base price
    assert pr.SIZE_UPLIFT == {"A4": Decimal("-5.00"), "A3": Decimal("0.00"), "A2": Decimal("10.00"), "A1": Decimal("25.00")}
    cheap = pr.build_product_payload(_gen(), image_url=IMAGE_URL, base_price=Decimal("10"))
    assert [v["price"] for v in cheap["variants"]] == ["5.00", "10.00", "20.00", "35.00"]


def test_stock_items(pr):
    assert pr.build_stock_items(_gen(), name="Custom: x", stock=1000) == [
        {"sku": "AI-7-A4", "name": "Custom: x (A4)", "available": 1000},
        {"sku": "AI-7-A3", "name": "Custom: x (A3)", "available": 1000},
        {"sku": "AI-7-A2", "name": "Custom: x (A2)", "available": 1000},
        {"sku": "AI-7-A1", "name": "Custom: x (A1)", "available": 1000},
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _run(pr, db, gen, catalog, inventory):
    return asyncio.run(pr.print_generation(
        db, gen, catalog=catalog, inventory=inventory, image_url=IMAGE_URL,
        base_price=Decimal("29.99"), stock=1000,
    ))


def test_print_generation_happy_path(pr):
    log, db, gen = [], MagicMock(), _gen()
    catalog, inventory = FakeCatalog(log), FakeInventory(log)
    assert _run(pr, db, gen, catalog, inventory) == ("AI-7", True)
    assert catalog.calls == [EXPECTED_PAYLOAD]
    assert len(inventory.calls) == 1 and len(inventory.calls[0]) == 4
    assert inventory.calls[0] == pr.build_stock_items(gen, name=EXPECTED_PAYLOAD["name"], stock=1000)
    assert log == ["catalog", "inventory"]  # catalog first, then inventory
    assert gen.catalog_product_sku == "AI-7"
    db.commit.assert_called_once()


def test_print_generation_idempotent(pr):
    log, db, gen = [], MagicMock(), _gen(catalog_product_sku="AI-7")
    catalog, inventory = FakeCatalog(log), FakeInventory(log)
    assert _run(pr, db, gen, catalog, inventory) == ("AI-7", False)
    assert catalog.calls == [] and inventory.calls == []
    db.commit.assert_not_called()


def test_print_generation_inventory_failure_leaves_null(pr, d):
    log, db, gen = [], MagicMock(), _gen()
    catalog = FakeCatalog(log)
    inventory = FakeInventory(log, fail=d.inventory_client.InventoryServiceError("down"))
    with pytest.raises(d.inventory_client.InventoryServiceError):
        _run(pr, db, gen, catalog, inventory)
    assert len(catalog.calls) == 1  # the family exists; the retry gets a 200 from catalog and creates the stock
    assert gen.catalog_product_sku is None
    db.commit.assert_not_called()


def test_print_generation_catalog_failure_skips_inventory(pr, d):
    log, db, gen = [], MagicMock(), _gen()
    catalog = FakeCatalog(log, fail=d.catalog_client.CatalogServiceError("down"))
    inventory = FakeInventory(log)
    with pytest.raises(d.catalog_client.CatalogServiceError):
        _run(pr, db, gen, catalog, inventory)
    assert inventory.calls == []
    assert gen.catalog_product_sku is None
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@pytest.fixture
def session(main):
    s = MagicMock()
    main.app.dependency_overrides[main.get_db] = lambda: s
    main.app.dependency_overrides[main.get_current_user_claims] = lambda: CLAIMS
    yield s
    main.app.dependency_overrides.clear()


def _found(session, gen):
    session.execute.return_value.scalar_one_or_none.return_value = gen


def test_print_route_status_codes(client, session, main, d, monkeypatch):
    catalog_mock = AsyncMock(return_value={"sku": "AI-7"})
    inventory_mock = AsyncMock(return_value={"created": [], "skipped": []})
    monkeypatch.setattr(d.catalog_client, "create_product_family", catalog_mock)
    monkeypatch.setattr(d.inventory_client, "create_stock", inventory_mock)

    # ready + owned + not printed -> 201 created
    gen = _gen()
    _found(session, gen)
    resp = client.post("/generations/7/print")
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"sku": "AI-7", "product_url": "/shop/product/AI-7", "created": True}
    assert catalog_mock.await_args.args[0]["sku"] == "AI-7"
    assert catalog_mock.await_args.args[0]["image_url"] == IMAGE_URL
    assert [i["sku"] for i in inventory_mock.await_args.args[0]] == ["AI-7-A4", "AI-7-A3", "AI-7-A2", "AI-7-A1"]
    assert gen.catalog_product_sku == "AI-7"
    session.commit.assert_called_once()

    # already printed -> 200, nothing called again
    catalog_mock.reset_mock(); inventory_mock.reset_mock(); session.commit.reset_mock()
    _found(session, _gen(catalog_product_sku="AI-7"))
    resp = client.post("/generations/7/print")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sku": "AI-7", "product_url": "/shop/product/AI-7", "created": False}
    catalog_mock.assert_not_awaited(); inventory_mock.assert_not_awaited(); session.commit.assert_not_called()

    # not ready -> 409
    for not_ready in (_gen(status="queued", image_key=None), _gen(status="failed", image_key=None), _gen(status="ready", image_key=None)):
        _found(session, not_ready)
        resp = client.post("/generations/7/print")
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == "Generation is not ready"
    catalog_mock.assert_not_awaited()

    # not owned / missing -> 404
    _found(session, None)
    assert client.post("/generations/7/print").status_code == 404

    # catalog outage -> 503, row stays retryable
    gen = _gen()
    _found(session, gen)
    catalog_mock.side_effect = d.catalog_client.CatalogServiceError("down")
    resp = client.post("/generations/7/print")
    assert resp.status_code == 503, resp.text
    assert gen.catalog_product_sku is None
    session.commit.assert_not_called()

    # open breaker -> 503
    catalog_mock.side_effect = d.circuit_breaker.CircuitOpenError("catalog")
    assert client.post("/generations/7/print").status_code == 503

    # inventory outage after a successful catalog call -> 503, row stays retryable
    catalog_mock.side_effect = None
    inventory_mock.side_effect = d.inventory_client.InventoryServiceError("down")
    gen = _gen()
    _found(session, gen)
    assert client.post("/generations/7/print").status_code == 503
    assert gen.catalog_product_sku is None

    # a downstream refusal (4xx) -> 502 carrying the detail
    inventory_mock.side_effect = None
    catalog_mock.side_effect = d.catalog_client.CatalogRejectedError("catalog 400: Unknown format 'A5'")
    resp = client.post("/generations/7/print")
    assert resp.status_code == 502, resp.text
    assert "Unknown format 'A5'" in resp.json()["detail"]


def test_print_route_requires_token(main, d):
    main.app.dependency_overrides.clear()
    c = TestClient(main.app)
    assert c.post("/generations/7/print").status_code == 401
