"""Regression guard for the 2026-09-18 liveness-probe kills: a sync SQLAlchemy call
inside an `async def` runs on the uvicorn event loop and blocks /healthz. Every such
call must sit in a nested sync def invoked through run_in_threadpool / asyncio.to_thread
(services/*/database.py carries the matching runtime tripwire)."""

import ast
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[2] / "services"
AUDITED = {
    "orders": [
        "main.py",
        "outbox.py",
        "escrow_reconciler.py",
        "status_metrics.py",
        "order_paid.py",
        "stripe_webhook.py",
    ],
    "catalog": ["main.py"],
    "designs": ["main.py", "style_profile.py", "printing.py", "worker.py"],
    "logistics": ["main.py"],
    "production": ["main.py", "status_metrics.py"],
    "inventory": ["main.py"],
}
DB_METHODS = {
    "get",
    "execute",
    "query",
    "flush",
    "commit",
    "rollback",
    "refresh",
    "scalar",
    "scalars",
    "merge",
    "delete",
    "add_all",
}


def on_loop_db_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), str(path))
    hits, seen = [], set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        inner = set()
        for n in ast.walk(fn):
            if isinstance(n, (ast.FunctionDef, ast.Lambda)) and n is not fn:
                inner.update(id(m) for m in ast.walk(n))
        for n in ast.walk(fn):
            if (
                id(n) in inner
                or not isinstance(n, ast.Call)
                or not isinstance(n.func, ast.Attribute)
            ):
                continue
            base = n.func.value
            name = base.id if isinstance(base, ast.Name) else None
            hit = (name in ("db", "conn") and n.func.attr in DB_METHODS) or (
                name == "engine" and n.func.attr == "connect"
            )
            if hit and n.lineno not in seen:
                seen.add(n.lineno)
                hits.append(
                    f"{path.relative_to(SERVICES.parent)}:{n.lineno}: "
                    f"in async {fn.name}(): {ast.unparse(n)[:90]}"
                )
    return hits


@pytest.mark.parametrize("service", sorted(AUDITED), ids=sorted(AUDITED))
def test_no_sync_sqlalchemy_inside_async_def(service):
    hits = [h for f in AUDITED[service] for h in on_loop_db_calls(SERVICES / service / f)]
    assert not hits, f"{len(hits)} SQLAlchemy call(s) on the event loop:\n" + "\n".join(hits)
