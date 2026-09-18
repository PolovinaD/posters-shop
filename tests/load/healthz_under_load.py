#!/usr/bin/env python3
"""healthz under load — runnable against the docker compose stack.

On the 2026-09-18 EKS run, ~50 concurrent k6 clients got the catalog and orders pods
SIGKILLed by their own liveness probes: sync SQLAlchemy calls inside `async def`
handlers block the uvicorn event loop, so `GET /healthz` cannot get the loop to send
its 20-byte answer and the kubelet's 1 s probe timeout expires. This script reproduces
the mechanism locally: N concurrent clients POST /orders for D seconds while a sampler
probes /healthz every 200 ms, and it reports the healthz p50/p95/max next to the order
throughput and error rate. Stdlib + httpx only.

    .venv/bin/python tests/load/healthz_under_load.py --clients 50 --duration 60 \
        --assert-p95-ms 250 --out /tmp/healthz-after.json
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone

import httpx

ORDER_BODY = {
    "customer_email": "admin@postershop.com",
    "payment_method": "stripe",
    "items": [{"sku": "POSTER-SUNSET-A3", "quantity": 1}],
    "shipping_address": {
        "recipient_name": "Load Test",
        "street": "Bulevar kralja Aleksandra 73",
        "city": "Beograd",
        "postal_code": "11000",
        "country": "Serbia",
        "phone": "+381601234567",
    },
}


def main() -> int:
    args = parse_args()
    token = login(args.users, args.email, args.password)
    if args.restock > 0:
        restock(args.inventory, args.sku, args.restock, token)
    body = dict(ORDER_BODY, customer_email=args.email, items=[{"sku": args.sku, "quantity": 1}])
    summary = asyncio.run(run(args, token, body))
    summary["command"] = " ".join(sys.argv)
    report(summary)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(summary, fh, indent=2)
        print(f"summary written to {args.out}")
    if args.assert_p95_ms is not None and summary["healthz"]["p95_ms"] > args.assert_p95_ms:
        print(f"FAIL: healthz p95 {summary['healthz']['p95_ms']} ms > {args.assert_p95_ms} ms")
        return 2
    return 0


async def run(args, token: str, body: dict) -> dict:
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    deadline = time.perf_counter() + args.duration
    orders: list[tuple[int, float]] = []
    healthz: list[float] = []
    failures = [0]
    auth = {"Authorization": f"Bearer {token}"}
    limits = httpx.Limits(
        max_connections=args.clients + 10, max_keepalive_connections=args.clients + 10
    )
    async with httpx.AsyncClient(timeout=30, limits=limits) as client, httpx.AsyncClient(
        timeout=5.0
    ) as probe:
        writers = [writer(client, args.base, body, auth, deadline, orders) for _ in range(args.clients)]
        await asyncio.gather(
            sampler(probe, args.base, args.healthz_interval, deadline, healthz, failures),
            *writers,
        )
    elapsed = args.duration
    by_status: dict[str, int] = {}
    for status, _ in orders:
        by_status[str(status)] = by_status.get(str(status), 0) + 1
    order_lat = sorted(ms for _, ms in orders)
    errors = sum(1 for status, _ in orders if status != 201)
    return {
        "base": args.base,
        "clients": args.clients,
        "duration": args.duration,
        "started_at": started_at,
        "healthz": {
            "samples": len(healthz) + failures[0],
            "failures": failures[0],
            "p50_ms": percentile(sorted(healthz), 50),
            "p95_ms": percentile(sorted(healthz), 95),
            "max_ms": round(max(healthz), 1) if healthz else None,
        },
        "orders": {
            "total": len(orders),
            "by_status": dict(sorted(by_status.items())),
            "per_second": round(len(orders) / elapsed, 1),
            "error_rate_pct": round(100.0 * errors / len(orders), 2) if orders else None,
            "p50_ms": percentile(order_lat, 50),
            "p95_ms": percentile(order_lat, 95),
        },
    }


async def writer(client, base, body, auth, deadline, out: list) -> None:
    while time.perf_counter() < deadline:
        t = time.perf_counter()
        try:
            r = await client.post(f"{base}/orders", json=body, headers=auth)
            status = r.status_code
        except httpx.HTTPError:
            status = 0
        out.append((status, (time.perf_counter() - t) * 1000))


async def sampler(probe, base, interval, deadline, out: list, failures: list) -> None:
    """One probe per tick, fired whether or not the previous one has answered (a blocked
    service would otherwise turn every 5 s timeout into 25 missing samples)."""
    probes = []
    while time.perf_counter() < deadline:
        t = time.perf_counter()
        probes.append(asyncio.ensure_future(probe_once(probe, base, out, failures)))
        await asyncio.sleep(max(0.0, interval - (time.perf_counter() - t)))
    await asyncio.gather(*probes)


async def probe_once(probe, base, out: list, failures: list) -> None:
    t = time.perf_counter()
    try:
        r = await probe.get(f"{base}/healthz")
        if r.status_code == 200:
            out.append((time.perf_counter() - t) * 1000)
        else:
            failures[0] += 1
    except httpx.HTTPError:
        failures[0] += 1


def login(users: str, email: str, password: str) -> str:
    with httpx.Client(timeout=10) as c:
        r = c.post(f"{users}/login", json={"email": email, "password": password})
    if r.status_code != 200:
        sys.exit(f"login failed: {r.status_code} {r.text}")
    return r.json()["access_token"]


def restock(inventory: str, sku: str, quantity: int, token: str) -> None:
    with httpx.Client(timeout=10) as c:
        r = c.post(
            f"{inventory}/stock/{sku}/restock",
            params={"quantity": quantity},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 404:
        sys.exit("SKU not seeded: POST /seed on catalog and inventory first")
    if r.status_code >= 300:
        sys.exit(f"restock failed: {r.status_code} {r.text}")


def percentile(sorted_values: list, pct: int):
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, int(round(pct / 100.0 * (len(sorted_values) - 1))))
    return round(sorted_values[idx], 1)


def report(s: dict) -> None:
    h, o = s["healthz"], s["orders"]
    print(f"command:   {s['command']}")
    print(f"target:    {s['base']}  clients={s['clients']}  duration={s['duration']}s  started={s['started_at']}")
    print(f"healthz:   samples={h['samples']:<5} failures={h['failures']:<4} p50={h['p50_ms']} ms  p95={h['p95_ms']} ms  max={h['max_ms']} ms")
    print(f"orders:    total={o['total']:<6} per_second={o['per_second']:<7} error_rate={o['error_rate_pct']}%  p50={o['p50_ms']} ms  p95={o['p95_ms']} ms")
    print(f"           by_status={o['by_status']}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://localhost:8003", help="orders service base URL")
    p.add_argument("--users", default="http://localhost:8001", help="users service base URL (login)")
    p.add_argument("--inventory", default="http://localhost:8006", help="inventory service base URL (restock)")
    p.add_argument("--sku", default="POSTER-SUNSET-A3")
    p.add_argument("--clients", type=int, default=50, help="concurrent POST /orders writers")
    p.add_argument("--duration", type=float, default=60, help="seconds")
    p.add_argument("--healthz-interval", type=float, default=0.2, help="seconds between /healthz probes")
    p.add_argument("--restock", type=int, default=200000, help="units to add before the run (0 = skip)")
    p.add_argument("--email", default="admin@postershop.com")
    p.add_argument("--password", default="admin1234")
    p.add_argument("--assert-p95-ms", type=float, default=None, help="exit 2 when the healthz p95 exceeds this")
    p.add_argument("--out", default=None, help="write the summary dict as JSON to this file")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main())
