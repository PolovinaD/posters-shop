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

| run | healthz p50 ms | p95 ms | max ms | failures | orders/s | created/s | error % |
|-----|----------------|--------|--------|----------|----------|-----------|---------|
| before (2026-09-18, 50 clients, 60 s) | 110.5 | 292.7 | 292.7 | 295 of 298 probes timed out | 1.7 | 0.0 | 100.0 (all 100 requests hit the 30 s client timeout) |
| after (2026-09-18, 50 clients, 60 s) | 31.3 | 129.2 | 769.9 | 0 of 287 | 86.8 | 1.6 | 98.14 (97 x 201, 5103 x 503 catalog circuit open, 10 x timeout — see below) |
| after, 20 clients, 30 s | 49.6 | 104.1 | 262.4 | 0 of 150 | 39.1 | 39.1 | 0.0 |
| bulkhead (2026-09-19, 50 clients, 60 s) | 28.9 | 105.0 | 431.7 | 0 of 299 | 26.4 | 26.4 | 0.0 (1587 x 201, 0 x 503 shed (Retry-After), order p50 1668 ms / p95 3201 ms) |
| bulkhead, 20 clients, 30 s | 13.9 | 94.2 | 385.4 | 0 of 149 | 18.5 | 18.5 | 0.0 (556 x 201, 0 x 503 shed (Retry-After), order p50 1042 ms / p95 1618 ms) |
| bulkhead, orders `BULKHEAD_LIMIT=16` (experiment, not the default; 50 clients, 60 s) | 45.1 | 208.4 | 375.2 | 0 of 299 | 22.4 | 22.4 | 0.0 (1341 x 201, 0 x 503 shed (Retry-After), order p50 2137 ms / p95 3870 ms) |
| bulkhead, 50 clients, 60 s, after the active reservations and the outbox had drained | 27.5 | 125.2 | 602.2 | 0 of 299 | 24.7 | 24.7 | 0.0 (1481 x 201, 0 x 503 shed (Retry-After), order p50 1832 ms / p95 3511 ms) |

`burst.py`: 2 x 50 concurrent `/internal/resolve-prices` against catalog -> 100 x 200,
0 shed, p50 660 ms (round 1) / 148 ms (round 2), max 740 ms; was 10 x 200 at 30.5 s +
40 x 500. `bulkhead_rejected_total` stayed 0.0 on catalog, inventory and orders through
all four healthz runs, and the event-loop tripwire stayed silent.

The `orders/s` column counts every answered request (an open circuit fast-fails at a
high rate); `created/s` counts only 201s. The first three bulkhead rows were measured
back-to-back on one compose stack and are not a clean throughput comparison: inventory
`POST /reserve` hydrates every active reservation on every call (`_update_metrics` in
`services/inventory/main.py`), and the active set grew from 0 to 3484 across the three
runs (1587 + 1341 + 556, all still inside their 15-min TTL), so its p50 went 33 ms in
the first run -> 116 ms in the second -> 161 ms in the third, the first and third at
the same (<= 8) inventory concurrency. That, not the bulkhead, is why the 20-client row
reads 18.5 instead of 39.1 (the 2026-09-18 run started from ~200 active reservations,
today's from 2928) and why the limit-16 experiment could not be judged on throughput
alone; its healthz p95 (208 ms vs 105 ms at the default 8) is the reason the committed
default stays engine-derived. The last row is the clean number: after the 3484
reservations had expired (the expiry sweep fanned ~1500 notifications at once into
orders' 8-slot bulkhead — `bulkhead_queued` peaked at 175, `bulkhead_rejected_total`
stayed 0) and the 2500 ORDER_CANCELLED outbox events had been delivered, the same
50-client run gave 24.7 created/s with reserve back at p50 39 ms. At 8 admitted
requests the pipeline does ~25 orders/s on this compose VM; the 30/s target was not
reached, and whether 16 would help needs the limit-16 run repeated on a drained stack.

Before the fix the orders container did not recover on its own: with no liveness probe
in compose it stayed parked in `pool_timeout=30` (5 s since the bulkhead) waits on the event loop at 0 % CPU and
had to be restarted by hand.

What changed between the rows: every SQLAlchemy call in an `async def` handler or
lifespan loop now runs through `run_in_threadpool` / `asyncio.to_thread`, `/healthz` is a
pure async handler, `/readyz` is bounded at 2 s, and every chart's probes carry
`timeoutSeconds: 5` (the kubelet default is 1 s). The liveness probe is the deliverable:
it answers throughout the run instead of timing out 295 times.

The 50-client order error rate is a second, separate defect that the fix exposes rather
than causes: FastAPI runs `def` handler bodies and response validation on one 40-token
threadpool, and each service's pool is 8-10 connections with `pool_timeout=30` (5 s since the bulkhead). When a
burst parks 40 threads in pool waits, the connection holders cannot get a token to
serialise their response and release the connection, so the whole batch fails after
30 s (reproduced on catalog alone: 50 concurrent `/internal/resolve-prices` -> 10 x 200
after 30.5 s, 40 x 500, ten sessions `idle in transaction` the whole time). Orders then
opens its catalog circuit and answers 503 fast for the rest of the run. Below that
threshold (20 clients) the pipeline is clean: 0 % errors at 39 orders/s.

Since 2026-09-19 every DB-backed service wraps its routes in a per-process bulkhead
(`services/shared/bulkhead.py`, innermost middleware, registered before
LoggingMiddleware): an `asyncio.Semaphore` sized to `pool_size + max_overflow` (8 for
orders, 10 elsewhere; `BULKHEAD_LIMIT` overrides) admits at most that many requests at
once, and a request that waits longer than `BULKHEAD_QUEUE_TIMEOUT` (10 s) for a slot
is answered `503 {"detail": "Service busy, retry shortly"}` with `Retry-After: 1` on
the event loop, without a thread or a connection. Excess requests therefore wait on
the loop instead of holding a threadpool token inside a pool wait, so the connection
holders always finish and release, `pool_timeout` dropped from 30 s to 5 s because a
pool wait is now a fault rather than a burst, and the gauges `bulkhead_in_flight` /
`bulkhead_queued` and the counter `bulkhead_rejected_total` on each `/metrics` show
the queue: the catalog burst that used to end as 10 x 200 at 30.5 s + 40 x 500 now
ends as 100 x 200 with a 740 ms maximum, and the 50-client run went from 98 % errors
to 0 % with 0 sheds. A shed answered by a downstream (catalog or inventory) still
counts as a circuit-breaker failure in orders, like any other 5xx (unchanged), and the
orders client timeout (10 s) equals the queue timeout, so orders never waits on a
downstream queue longer than it would wait on a slow downstream anyway (a request
queued for the full window is shed at about the moment the caller gives up; either
way it is one breaker failure, not a 30 s hang).

## burst (compose)

The isolated reproduction of the deadlock, now the bulkhead's regression check: N
concurrent identical requests per round against one endpoint, the next round starting
as soon as the previous one completes.

```bash
.venv/bin/python tests/load/burst.py --url http://localhost:8002/internal/resolve-prices \
    --concurrency 50 --rounds 2 --out /tmp/burst-catalog.json
```

Options that matter: `--concurrency 50` (requests fired at once per round),
`--rounds 2`, `--body '{"skus": ["POSTER-SUNSET-A3"]}'` (JSON; `--method POST` by
default). One owner login per invocation (`--users`, `--email`, `--password`). Prints
a status histogram plus p50/p95/max per round; a 503 carrying `Retry-After` is
counted as a shed, and the exit status is 1 if any request failed at the transport
level or answered a 5xx that is not a shed.
