#!/usr/bin/env python3
"""burst — N concurrent identical requests per round against one endpoint.

The isolated reproduction of the threadpool-token starvation deadlock: 50 concurrent
`POST /internal/resolve-prices` against catalog, a second burst right after the first.
Before the bulkhead a round ended as 10 x 200 at 30.5 s + 40 x 500; with it every
request is either admitted (200) or shed fast (503 + Retry-After). Prints a status
histogram and p50/p95/max per round, exits 1 on any transport failure or 5xx that is
not a shed. Stdlib + httpx only.

    .venv/bin/python tests/load/burst.py --url http://localhost:8002/internal/resolve-prices \
        --concurrency 50 --rounds 2 --out /tmp/burst-catalog.json
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter

import httpx


def main() -> int:
    args = parse_args()
    token = login(args.users, args.email, args.password)
    body = json.loads(args.body)
    result = asyncio.run(run(args, token, body))
    result["command"] = " ".join(sys.argv)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=2)
        print(f"summary written to {args.out}")
    return 1 if result["failed"] else 0


async def run(args, token: str, body: dict) -> dict:
    auth = {"Authorization": f"Bearer {token}"}
    limits = httpx.Limits(max_connections=args.concurrency + 5)
    rounds = []
    total: Counter = Counter()
    failed = 0
    async with httpx.AsyncClient(timeout=35, limits=limits) as client:
        for n in range(1, args.rounds + 1):
            wall = time.perf_counter()
            results = await asyncio.gather(
                *(one(client, args.method, args.url, body, auth) for _ in range(args.concurrency))
            )
            wall = time.perf_counter() - wall
            by_status = Counter(status for status, _, _ in results)
            shed = sum(1 for _, _, s in results if s)
            bad = sum(1 for status, _, s in results if (status == 0 or status >= 500) and not s)
            lat = sorted(ms for _, ms, _ in results)
            r = {
                "by_status": {str(k): v for k, v in sorted(by_status.items())},
                "shed": shed,
                "p50_ms": percentile(lat, 50),
                "p95_ms": percentile(lat, 95),
                "max_ms": percentile(lat, 100),
                "wall_s": round(wall, 2),
            }
            rounds.append(r)
            total.update(by_status)
            failed += bad
            print(
                f"round {n}: {dict(by_status)} shed={shed} p50={r['p50_ms']} ms "
                f"p95={r['p95_ms']} ms max={r['max_ms']} ms wall={r['wall_s']} s"
            )
    print(f"total: {dict(total)} shed={sum(r['shed'] for r in rounds)} failed={failed}")
    return {"url": args.url, "concurrency": args.concurrency, "rounds": rounds, "failed": failed}


async def one(client, method: str, url: str, body: dict, auth: dict) -> tuple[int, float, bool]:
    t = time.perf_counter()
    try:
        r = await client.request(method, url, json=body, headers=auth)
        status, shed = r.status_code, r.status_code == 503 and "retry-after" in r.headers
    except httpx.HTTPError:
        status, shed = 0, False
    return status, (time.perf_counter() - t) * 1000, shed


def login(users: str, email: str, password: str) -> str:
    with httpx.Client(timeout=10) as c:
        r = c.post(f"{users}/login", json={"email": email, "password": password})
    if r.status_code != 200:
        sys.exit(f"login failed: {r.status_code} {r.text}")
    return r.json()["access_token"]


def percentile(sorted_values: list, pct: int):
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, int(round(pct / 100.0 * (len(sorted_values) - 1))))
    return round(sorted_values[idx], 1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True, help="e.g. http://localhost:8002/internal/resolve-prices")
    p.add_argument("--method", default="POST")
    p.add_argument("--body", default='{"skus": ["POSTER-SUNSET-A3"]}', help="JSON request body")
    p.add_argument("--concurrency", type=int, default=50, help="identical requests fired at once per round")
    p.add_argument("--rounds", type=int, default=2, help="rounds, each starting as soon as the previous completes")
    p.add_argument("--users", default="http://localhost:8001", help="users service base URL (login)")
    p.add_argument("--email", default="admin@postershop.com")
    p.add_argument("--password", default="admin1234")
    p.add_argument("--out", default=None, help="write the per-round results as JSON to this file")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main())
