# Load test (k6)

Stepped load against a live cluster's ALB: one `constant-vus` k6 run per step, a
summary JSON per step, and a sampler that records ready replicas + HPA values every
10 s. Two paths: `read` = `GET /api/catalog/products`, `write` = `POST /api/orders/orders`
(one `POSTER-SUNSET-A3` per order, owner token, restock the SKU first).

```bash
brew install k6
ALB=http://<alb-hostname>
TOKEN=...  # owner
curl -s -X POST "$ALB/api/inventory/stock/POSTER-SUNSET-A3/restock?quantity=200000" -H "Authorization: Bearer $TOKEN"
KINDS="read write" tests/load/run.sh "$ALB" /tmp/loadtest 90s "10 50 100 200"
python3 tests/load/summarize.py /tmp/loadtest      # markdown table per step
```

Results from the first run (2026-09-18) are in `thesis-build/evidence/eks-2026-09-18/loadtest/`:
at ~50 concurrent clients the catalog and orders pods were killed by their liveness probes
(sync SQLAlchemy calls inside `async def` handlers block the event loop, so `/healthz`
starves) and the ALB shed traffic with 503s — see `thesis-build/evidence/eks-2026-09-18/`.

## healthz under load (compose)

Reproduces the 2026-09-18 liveness-kill mechanism locally: 50 concurrent clients
`POST /orders` for 60 s while `GET /healthz` is probed every 200 ms, and reports the
probe latency next to the order throughput.

```bash
.venv/bin/python tests/load/healthz_under_load.py --assert-p95-ms 250 --out /tmp/healthz.json
```

Options: `--base` (orders, default `http://localhost:8003`), `--users` (`:8001`, one login
per run — `/login` is rate-limited 10/min), `--inventory` (`:8006`), `--sku`
(`POSTER-SUNSET-A3`), `--clients 50`, `--duration 60`, `--healthz-interval 0.2`,
`--restock 200000` (units added before the run; `0` skips; 404 means the SKU is not
seeded — `POST /seed` on catalog and inventory first), `--email` / `--password` (owner),
`--assert-p95-ms N` (exit 2 when the healthz p95 exceeds it), `--out FILE` (summary JSON).
A probe is fired every tick whether or not the previous one answered; a probe that
times out (5 s) counts as a failure, percentiles are over the answered probes.
Every order leaves a 15-min inventory reservation that the expiry worker cancels later.

| run | healthz p50 ms | p95 ms | max ms | failures | orders/s | error % |
|-----|----------------|--------|--------|----------|----------|---------|
| before (2026-09-18, 50 clients, 60 s) | 110.5 | 292.7 | 292.7 | 295 of 298 probes timed out | 1.7 | 100.0 (all 100 requests hit the 30 s client timeout) |
| after (2026-09-18, 50 clients, 60 s) | 31.3 | 129.2 | 769.9 | 0 of 287 | 86.8 | 98.14 (97 x 201, 5103 x 503 catalog circuit open, 10 x timeout — see below) |
| after, 20 clients, 30 s | 49.6 | 104.1 | 262.4 | 0 of 150 | 39.1 | 0.0 |

Before the fix the orders container did not recover on its own: with no liveness probe
in compose it stayed parked in `pool_timeout=30` waits on the event loop at 0 % CPU and
had to be restarted by hand.

What changed between the rows: every SQLAlchemy call in an `async def` handler or
lifespan loop now runs through `run_in_threadpool` / `asyncio.to_thread`, `/healthz` is a
pure async handler, `/readyz` is bounded at 2 s, and every chart's probes carry
`timeoutSeconds: 5` (the kubelet default is 1 s). The liveness probe is the deliverable:
it answers throughout the run instead of timing out 295 times.

The 50-client order error rate is a second, separate defect that the fix exposes rather
than causes: FastAPI runs `def` handler bodies and response validation on one 40-token
threadpool, and each service's pool is 8-10 connections with `pool_timeout=30`. When a
burst parks 40 threads in pool waits, the connection holders cannot get a token to
serialise their response and release the connection, so the whole batch fails after
30 s (reproduced on catalog alone: 50 concurrent `/internal/resolve-prices` -> 10 x 200
after 30.5 s, 40 x 500, ten sessions `idle in transaction` the whole time). Orders then
opens its catalog circuit and answers 503 fast for the rest of the run. Below that
threshold (20 clients) the pipeline is clean: 0 % errors at 39 orders/s.
