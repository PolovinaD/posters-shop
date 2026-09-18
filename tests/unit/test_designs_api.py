"""Route tests for services/designs/main.py with TestClient (no `with` block, so the
lifespan — and the worker task — never runs), the JWT dependency overridden with fixed
claims and get_db overridden with a MagicMock session (test_payments_escrow.py pattern).
Only the paths the routes read are configured on the mock."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from tests.unit.designs_testkit import load_designs

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
CLAIMS = {"sub": "c@x.io", "role": "customer"}
OWNER = {"sub": "admin@x.io", "role": "owner"}
KEY = "0" * 32 + ".png"


@pytest.fixture(scope="module")
def d():
    return load_designs()


@pytest.fixture(scope="module")
def main(d):
    return d.main


@pytest.fixture(scope="module")
def client(main):
    return TestClient(main.app)


@pytest.fixture
def session(main):
    s = MagicMock()
    s.execute.return_value.scalar.return_value = 0
    main.app.dependency_overrides[main.get_db] = lambda: s
    main.app.dependency_overrides[main.get_current_user_claims] = lambda: CLAIMS
    yield s
    main.app.dependency_overrides.clear()


def _gen(**over):
    base = dict(
        id=5, customer_email="c@x.io", prompt="p", effective_prompt="p", personalise=False,
        provider="fake", status="queued", failure_reason=None, image_key=None, attempts=0,
        retry_after=None, created_at=NOW, started_at=None, finished_at=None, purchased_at=None,
        catalog_product_sku=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _refresh_as(session, **attrs):
    def side_effect(obj):
        for k, v in attrs.items():
            setattr(obj, k, v)
    session.refresh.side_effect = side_effect


def _last_sql(session):
    """The last statement handed to session.execute, rendered as literal PostgreSQL."""
    return str(session.execute.call_args[0][0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))


def test_post_generation_202_queued(client, session, d):
    _refresh_as(session, id=1, created_at=NOW)
    resp = client.post("/generations", json={"prompt": "a poster"})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["id"] == 1
    assert body["status"] == "queued"
    assert body["prompt"] == "a poster"
    assert body["effective_prompt"] == "a poster"
    assert body["personalise"] is False
    assert body["image_url"] is None
    assert body["provider"] == "fake"
    added = session.add.call_args[0][0]
    assert isinstance(added, d.models.Generation)
    assert added.customer_email == "c@x.io"  # from the JWT, never from the body
    assert added.status == "queued"
    session.commit.assert_called_once()


def test_post_generation_validates_prompt(client, session):
    assert client.post("/generations", json={"prompt": "ab"}).status_code == 422
    assert client.post("/generations", json={}).status_code == 422
    assert client.post("/generations", json={"prompt": "x" * 2001}).status_code == 422
    session.add.assert_not_called()


def test_post_generation_429_over_quota(client, session):
    session.execute.return_value.scalar.return_value = 10  # AI_DAILY_QUOTA default 10
    resp = client.post("/generations", json={"prompt": "a poster"})
    assert resp.status_code == 429
    assert resp.headers["Retry-After"].isdigit()
    assert resp.json()["detail"] == "Daily limit of 10 generations reached"
    session.add.assert_not_called()


def test_post_generation_owner_bypasses_quota(client, session, main):
    main.app.dependency_overrides[main.get_current_user_claims] = lambda: OWNER
    session.execute.return_value.scalar.return_value = 10
    _refresh_as(session, id=2, created_at=NOW)
    resp = client.post("/generations", json={"prompt": "a poster"})
    assert resp.status_code == 202, resp.text
    assert session.add.call_args[0][0].customer_email == "admin@x.io"


def test_get_generation_scoped_to_caller(client, session):
    session.execute.return_value.scalar_one_or_none.return_value = None
    assert client.get("/generations/5").status_code == 404

    session.execute.return_value.scalar_one_or_none.return_value = _gen(status="ready", image_key=KEY)
    resp = client.get("/generations/5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["image_url"] == "/api/designs/images/" + KEY
    assert body["product_url"] is None
    assert "image_key" not in body  # the storage key is not part of the API

    session.execute.return_value.scalar_one_or_none.return_value = _gen(
        status="ready", image_key=KEY, catalog_product_sku="AI-5"
    )
    body = client.get("/generations/5").json()
    assert body["product_url"] == "/shop/product/AI-5"
    assert body["catalog_product_sku"] == "AI-5"


def test_get_generation_no_image_url_until_ready(client, session):
    session.execute.return_value.scalar_one_or_none.return_value = _gen(status="generating")
    assert client.get("/generations/5").json()["image_url"] is None
    session.execute.return_value.scalar_one_or_none.return_value = _gen(status="failed", failure_reason="nope")
    body = client.get("/generations/5").json()
    assert body["image_url"] is None and body["failure_reason"] == "nope"


def test_list_generations_newest_first_query(client, session):
    row1, row2 = _gen(id=1), _gen(id=2)
    session.execute.return_value.scalars.return_value.all.return_value = [row2, row1]
    resp = client.get("/generations")
    assert resp.status_code == 200
    assert [g["id"] for g in resp.json()] == [2, 1]
    assert client.get("/generations?limit=0").status_code == 422
    assert client.get("/generations?limit=201").status_code == 422


def test_admin_generations_owner_sees_every_customer(client, session, main):
    main.app.dependency_overrides[main.get_current_user_claims] = lambda: OWNER
    session.execute.return_value.scalars.return_value.all.return_value = [
        _gen(id=9, customer_email="b@x.io", status="ready", image_key=KEY, attempts=2),
        _gen(id=3, customer_email="c@x.io", status="failed", failure_reason="nope", attempts=3),
    ]
    resp = client.get("/admin/generations")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [g["id"] for g in body] == [9, 3]
    assert [g["customer_email"] for g in body] == ["b@x.io", "c@x.io"]
    assert [g["attempts"] for g in body] == [2, 3]
    assert body[0]["image_url"] == "/api/designs/images/" + KEY  # derived through the shared to_out
    assert "image_key" not in body[0]
    sql = _last_sql(session)
    assert "customer_email =" not in sql  # NOT scoped to the caller
    assert "created_at DESC" in sql
    assert "LIMIT 100" in sql  # the default


def test_admin_generations_filters_and_limits(client, session, main):
    main.app.dependency_overrides[main.get_current_user_claims] = lambda: OWNER
    session.execute.return_value.scalars.return_value.all.return_value = []
    resp = client.get("/admin/generations?customer=c@x.io&status=failed&limit=7")
    assert resp.status_code == 200, resp.text
    sql = _last_sql(session)
    assert "customer_email = 'c@x.io'" in sql
    assert "status = 'failed'" in sql
    assert "LIMIT 7" in sql
    assert client.get("/admin/generations?limit=0").status_code == 422
    assert client.get("/admin/generations?limit=201").status_code == 422
    assert client.get("/admin/generations?status=bogus").status_code == 422


def test_admin_generations_customer_403(client, session):
    resp = client.get("/admin/generations")  # default session fixture: CLAIMS = customer
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Owner role required"
    session.execute.assert_not_called()


def test_images_route_serves_png(client, main, d):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    key = d.storage.new_image_key()
    main.storage().put(key, png)
    resp = client.get(f"/images/{key}")  # no Authorization header
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert resp.content == png
    head = client.head(f"/images/{key}")  # curl -I / browser probes
    assert head.status_code == 200
    assert head.headers["content-type"] == "image/png"
    assert head.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert head.content == b""


def test_images_route_404_and_bad_key(client, d):
    assert client.get(f"/images/{d.storage.new_image_key()}").status_code == 404
    assert client.get("/images/not-a-key").status_code in (404, 422)
    assert client.get("/images/..%2F..%2Fetc%2Fpasswd").status_code in (404, 422)
    assert client.get("/images/" + "A" * 32 + ".png").status_code in (404, 422)


def test_saved_prompts_crud(client, session, d):
    _refresh_as(session, id=3, created_at=NOW)
    resp = client.post("/saved-prompts", json={"title": "Sunsets", "prompt": "a sunset over the sea"})
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"id": 3, "title": "Sunsets", "prompt": "a sunset over the sea", "created_at": NOW.isoformat().replace("+00:00", "Z")}
    added = session.add.call_args[0][0]
    assert isinstance(added, d.models.SavedPrompt) and added.customer_email == "c@x.io"
    assert client.post("/saved-prompts", json={"title": "", "prompt": "a sunset over the sea"}).status_code == 422

    saved = SimpleNamespace(id=3, customer_email="c@x.io", title="Sunsets", prompt="a sunset over the sea", created_at=NOW)
    session.execute.return_value.scalars.return_value.all.return_value = [saved]
    resp = client.get("/saved-prompts")
    assert resp.status_code == 200 and [p["id"] for p in resp.json()] == [3]

    session.execute.return_value.scalar_one_or_none.return_value = saved
    assert client.delete("/saved-prompts/3").status_code == 204
    session.delete.assert_called_once_with(saved)

    session.delete.reset_mock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    assert client.delete("/saved-prompts/3").status_code == 404
    session.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(**{**vars(saved), "customer_email": "other@x.io"})
    assert client.delete("/saved-prompts/3").status_code == 404
    session.delete.assert_not_called()


def test_me_quota(client, session, main):
    session.execute.return_value.scalar.return_value = 3
    body = client.get("/me/quota").json()
    assert body["limit"] == 10 and body["used"] == 3 and body["remaining"] == 7 and body["exempt"] is False
    assert body["resets_at"].endswith("Z") or "+00:00" in body["resets_at"]

    main.app.dependency_overrides[main.get_current_user_claims] = lambda: OWNER
    body = client.get("/me/quota").json()
    assert body["exempt"] is True and body["remaining"] is None and body["used"] == 0


def test_routes_registered(main):
    routes = {(m, r.path) for r in main.app.routes for m in getattr(r, "methods", None) or ()}
    for expected in [
        ("POST", "/generations"), ("GET", "/generations"), ("GET", "/generations/{generation_id}"),
        ("GET", "/images/{key}"), ("GET", "/saved-prompts"), ("POST", "/saved-prompts"),
        ("DELETE", "/saved-prompts/{saved_prompt_id}"), ("GET", "/me/quota"),
        ("GET", "/me/style-profile"), ("POST", "/me/style-profile/refresh"), ("POST", "/events/order-paid"),
        ("GET", "/admin/generations"), ("GET", "/healthz"), ("GET", "/readyz"), ("GET", "/metrics"),
    ]:
        assert expected in routes, expected


def test_unauthenticated_requests_are_401(client, main):
    main.app.dependency_overrides.clear()
    for method, path in [
        ("GET", "/generations"), ("POST", "/generations"), ("GET", "/me/quota"), ("GET", "/saved-prompts"),
        ("GET", "/me/style-profile"), ("POST", "/me/style-profile/refresh"), ("GET", "/admin/generations"),
    ]:
        resp = client.request(method, path, json={"prompt": "a poster"} if method == "POST" else None)
        assert resp.status_code == 401, (method, path, resp.status_code)


def test_me_style_profile_get_and_refresh(client, session, main, d, monkeypatch):
    # no row yet: the defaults (no summary, stale) rather than a 404
    session.get.return_value = None
    assert client.get("/me/style-profile").json() == {
        "summary": None, "prompt_count": 0, "purchase_count": 0, "stale": True, "updated_at": None,
    }

    prof = SimpleNamespace(
        customer_email="c@x.io", summary="You lean towards: vintage.", prompt_count=4, purchase_count=1,
        stale=False, updated_at=NOW,
    )
    session.get.return_value = prof
    body = client.get("/me/style-profile").json()
    assert body["summary"] == "You lean towards: vintage." and body["stale"] is False
    assert (body["prompt_count"], body["purchase_count"]) == (4, 1)
    session.get.assert_called_with(d.models.StyleProfile, "c@x.io")

    # refresh delegates to style_profile.refresh_profile for the caller and answers its row
    calls = []

    async def fake_refresh(db, email, *a, **k):
        calls.append((db, email))
        return SimpleNamespace(summary="fresh", prompt_count=5, purchase_count=2, stale=False, updated_at=NOW)

    monkeypatch.setattr(main, "refresh_profile", fake_refresh)
    body = client.post("/me/style-profile/refresh").json()
    assert body["summary"] == "fresh" and body["stale"] is False and body["purchase_count"] == 2
    assert calls == [(session, "c@x.io")]
