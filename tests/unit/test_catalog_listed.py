"""
Unit tests for the catalog `listed` flag (D-13) and the service-token family create
`POST /internal/products` used by the designs service's Print-this (09-04).

No database or network: the route functions are called directly with a MagicMock
session whose `execute` captures the compiled statement, so the tests assert on the
SQL the route builds (`products.listed = true` present or absent) rather than on
rows.

Module isolation follows tests/unit/test_inventory_reservation.py: `database` and
`metrics` are stubbed (the real catalog metrics.py would re-register
http_requests_total and prometheus_client raises on the duplicate), `logger`,
`service_auth` and `auth` are loaded from services/catalog under bare names only
while main.py is being imported, and the bare names are popped afterwards.
"""
import asyncio
import importlib.util
import os
import re
import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy.orm import DeclarativeBase

_CATALOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/catalog"))


def _load_catalog_module(name: str):
    spec = importlib.util.spec_from_file_location(f"catalog_{name}", os.path.join(_CATALOG_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"catalog_{name}"] = mod
    sys.modules[name] = mod  # bare name while loading so main.py's intra-service imports hit this copy
    spec.loader.exec_module(mod)
    return mod


class _RealBase(DeclarativeBase):
    pass


async def _noop_track_metrics(request, call_next):
    return await call_next(request)


os.environ.setdefault("JWT_SECRET", "unit-test-secret")

_db_stub = types.ModuleType("database")
_db_stub.Base = _RealBase
_db_stub.engine = MagicMock()
_db_stub.get_db = MagicMock()
_db_stub.SessionLocal = MagicMock()
sys.modules["database"] = _db_stub

_metrics_stub = types.ModuleType("metrics")
_metrics_stub.SERVICE_NAME = "catalog"
_metrics_stub.track_metrics = _noop_track_metrics
_metrics_stub.metrics_endpoint = MagicMock(return_value="")
sys.modules["metrics"] = _metrics_stub

sys.path.insert(0, _CATALOG_DIR)
try:
    _load_catalog_module("logger")
    _load_catalog_module("service_auth")
    _load_catalog_module("auth")
    catalog_main = _load_catalog_module("main")
finally:
    sys.path.remove(_CATALOG_DIR)
    for _name in ("logger", "service_auth", "auth", "main", "metrics"):
        sys.modules.pop(_name, None)
    # "database" stays installed: main.py keeps a live reference to its get_db.

Product = catalog_main.Product
ProductVariant = catalog_main.ProductVariant
Size = catalog_main.Size


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _where(sql: str) -> str:
    """The WHERE clause only: the SELECT list names every column, `listed` included."""
    return sql.split("WHERE", 1)[1] if "WHERE" in sql else ""


def _injected_response() -> Response:
    """What FastAPI hands a route asking for `response: Response`: status_code unset."""
    response = Response()
    response.status_code = None
    return response


class FakeResult:
    """What `db.execute(...)` hands back: the test decides the scalar and the list."""

    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._scalar

    def __iter__(self):
        return iter(self._rows)


def _capturing_db(scalar=None, rows=None):
    """A session whose `execute` records the compiled SQL of every statement it sees."""
    db = MagicMock()
    db.captured = []

    def _execute(stmt, *args, **kwargs):
        db.captured.append(_sql(stmt))
        return FakeResult(scalar=scalar, rows=rows)

    db.execute.side_effect = _execute
    return db


def _product(sku="AI-1", listed=False, variants=()):
    product = Product(
        id=1, sku=sku, name="Custom: x", description="x", price=Decimal("24.99"),
        category="Custom", image_url="/api/designs/images/k.png", active=True, listed=listed,
    )
    for i, (size, price) in enumerate(variants, start=1):
        product.variants.append(ProductVariant(id=i, sku=f"{sku}-{size}", size=size, price=Decimal(price), active=True))
    return product


_FAMILY = [("A4", "24.99"), ("A3", "29.99"), ("A2", "39.99"), ("A1", "54.99")]


def _internal_payload(**overrides):
    data = {
        "sku": "AI-7", "name": "Custom: x", "description": "x", "category": "Custom",
        "image_url": "/api/designs/images/k.png", "listed": False,
        "variants": [{"size": s, "price": p} for s, p in _FAMILY],
    }
    data.update(overrides)
    return catalog_main.InternalProductCreate(**data)


def _family_create_db(known_sizes=("A4", "A3", "A2", "A1"), existing=None):
    """Session for the internal create: the sku lookup answers `existing`, `_known_size`
    answers a Size for every name in `known_sizes` (None otherwise), `add` assigns ids."""
    db = MagicMock()
    db.captured = []
    next_id = {"n": 100}

    def _execute(stmt, *args, **kwargs):
        sql = _sql(stmt)
        db.captured.append(sql)
        if "FROM catalog_schema.sizes" in sql:
            m = re.search(r"sizes\.name = '([^']+)'", sql)
            if m and m.group(1) in known_sizes:
                return FakeResult(scalar=Size(id=known_sizes.index(m.group(1)) + 1, name=m.group(1), sort_order=0))
            return FakeResult(scalar=None, rows=[Size(id=i + 1, name=n, sort_order=i) for i, n in enumerate(known_sizes)])
        return FakeResult(scalar=existing)

    def _add(obj):
        obj.id = next_id["n"]
        next_id["n"] += 1
        for v in getattr(obj, "variants", []) or []:
            v.id = next_id["n"]
            next_id["n"] += 1

    db.execute.side_effect = _execute
    db.add.side_effect = _add
    return db


def _route(path: str):
    for r in catalog_main.app.routes:
        if getattr(r, "path", None) == path:
            return r
    raise AssertionError(f"route {path} not registered")


# ---------------------------------------------------------------------------
# Model / schema
# ---------------------------------------------------------------------------

def test_product_model_has_listed_default_true():
    col = Product.__table__.c.listed
    assert col.default.arg is True
    assert col.nullable is False
    assert col.server_default is not None
    assert "listed" in catalog_main.ProductOut.model_fields
    assert catalog_main.ProductOut.model_fields["listed"].default is True
    assert catalog_main.ProductCreate.model_fields["listed"].default is True
    assert catalog_main.ProductUpdate.model_fields["listed"].default is None


# ---------------------------------------------------------------------------
# Read paths: grid + tabs filter, direct read + pricing do not
# ---------------------------------------------------------------------------

def test_list_products_filters_listed_by_default():
    db = _capturing_db()
    asyncio.run(catalog_main.list_products(db=db, include_stock=False))
    assert "products.listed = true" in _where(db.captured[0])

    db = _capturing_db()
    asyncio.run(catalog_main.list_products(db=db, include_stock=False, listed_only=False))
    assert "listed" not in _where(db.captured[0])
    assert "products.active = true" in _where(db.captured[0])  # active_only still applies


def test_list_categories_filters_listed():
    db = _capturing_db(rows=["Nature", "Custom"])
    out = catalog_main.list_categories(db=db)
    assert "products.listed = true" in _where(db.captured[0])
    assert "products.active = true" in _where(db.captured[0])
    assert out[0] == "All"


def test_get_product_and_resolve_prices_do_not_filter_listed():
    db = _capturing_db(scalar=_product(listed=False, variants=_FAMILY))
    out = asyncio.run(catalog_main.get_product("AI-1", include_stock=False, db=db))
    assert "listed" not in _where(db.captured[0])
    assert out.sku == "AI-1" and out.listed is False and len(out.variants) == 4

    db = _capturing_db()
    catalog_main.resolve_prices(catalog_main.PriceQuery(skus=["AI-1-A3"]), db=db, _={})
    assert db.captured, "resolve_prices must query the variants"
    assert all("listed" not in _where(sql) for sql in db.captured)


# ---------------------------------------------------------------------------
# POST /internal/products
# ---------------------------------------------------------------------------

def test_internal_products_creates_family_and_variants():
    db = _family_create_db()
    response = _injected_response()
    out = catalog_main.create_internal_product(_internal_payload(), response, db=db, _={})

    assert out.sku == "AI-7"
    assert out.listed is False
    assert out.category == "Custom"
    assert out.image_url == "/api/designs/images/k.png"
    assert [v.sku for v in out.variants] == ["AI-7-A4", "AI-7-A3", "AI-7-A2", "AI-7-A1"]
    assert [str(v.price) for v in out.variants] == ["24.99", "29.99", "39.99", "54.99"]
    assert out.price_from == Decimal("24.99")
    assert db.commit.call_count == 1
    assert response.status_code is None  # untouched -> the route's own 201 applies
    assert _route("/internal/products").status_code == 201


def test_internal_products_existing_sku_returns_existing():
    existing = _product(sku="AI-7", listed=False, variants=_FAMILY)
    db = _family_create_db(existing=existing)
    response = _injected_response()
    out = catalog_main.create_internal_product(_internal_payload(), response, db=db, _={})

    assert response.status_code == 200
    assert out.sku == "AI-7" and len(out.variants) == 4
    db.add.assert_not_called()
    db.commit.assert_not_called()
    assert len(db.captured) == 1  # only the sku lookup ran: no size lookups, nothing written


def test_internal_products_unknown_size_400():
    db = _family_create_db(known_sizes=("A4", "A3", "A2", "A1"))
    payload = _internal_payload(variants=[{"size": "A5", "price": "9.99"}, {"size": "A4", "price": "24.99"}])
    with pytest.raises(HTTPException) as exc:
        catalog_main.create_internal_product(payload, _injected_response(), db=db, _={})
    assert exc.value.status_code == 400
    assert exc.value.detail.startswith("Unknown format 'A5'")
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_internal_products_payload_validation():
    with pytest.raises(ValidationError):
        _internal_payload(variants=[])
    with pytest.raises(ValidationError):
        _internal_payload(sku="")
    payload = _internal_payload()
    assert payload.listed is False and payload.active is True and payload.category == "Custom"


def _guards(path: str, method: str) -> list[str]:
    route = [r for r in catalog_main.app.routes if getattr(r, "path", None) == path and method in r.methods][0]
    # the stubbed get_db is a MagicMock without __name__
    return [getattr(dep.call, "__name__", type(dep.call).__name__) for dep in route.dependant.dependencies]


def test_internal_products_requires_service_or_owner():
    names = _guards("/internal/products", "POST")
    assert "require_service_or_owner" in names
    assert "require_owner" not in names
    # the owner write paths are untouched
    assert "require_owner" in _guards("/products", "POST")
    assert "require_owner" in _guards("/products/{sku}/variants", "POST")
