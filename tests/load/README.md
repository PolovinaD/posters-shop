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
