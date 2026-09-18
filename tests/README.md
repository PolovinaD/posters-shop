# PosterShop Tests

## Unit Tests (no running services required)

```
pip install -r tests/requirements.txt
pytest tests/unit/ -v
```

| File | Covers |
|------|--------|
| `test_correlation_headers.py` | `correlation_headers()` and drift between `services/shared/logger.py` and the per-service copies |
| `test_inventory_reservation.py` | inventory reservation logic against a `MagicMock` SQLAlchemy session |
| `test_order_cancel.py` | orders `POST /orders/{id}/cancel` status validation (200 / 400 per `OrderStatus`) with stubbed clients |
| `test_order_state_machine.py` | `OrderStatus` transition table |
| `test_orders_status_gauge.py` | the `orders_by_status` Prometheus gauge worker |
| `test_logistics_worker.py` | `next_status` auto-advance rule |
| `test_stripe_payments.py` | payments Stripe endpoints with a mocked `stripe` SDK |
| `test_escrow_contract.py` | `OrderEscrow.json` artifact sanity: ABI functions/events present, `source_sha256` matches the committed `.sol` |
| `test_payments_escrow.py` | payments escrow provider (fake `Web3`) and the eight `/v1/escrow` routes (fake provider): deploy, state, invoice, courier, release, cancel, 409 / 404 / 503 mapping, Ganache revert phrasing |
| `test_orders_escrow.py` | orders escrow endpoints, `mark_order_paid`, cancel refund, CONTRACT B courier binding and the reconciler decision table, on a `FakeEscrow` payment client |
| `test_users_wallet.py` | `normalize_wallet` accepts `0x` + 40 hex and rejects everything else |
| `test_logistics_courier.py` | `courier_binding_wallet` (only `dispatched -> in_transit` binds; explicit wallet beats the default) |
| `test_logistics_courier_record.py` | `courier_id_from_claims` (JWT `sub` as-is, `None` for `service:` subjects) and the three audit columns (`courier_id`, `courier_wallet`, `courier_bound_at`) recorded on the pick-up paths |
| `test_designs_providers.py` | designs image providers: the fake Pillow placeholder and its `[reject]` / `[fail]` / `[slow]` hooks, `OpenAIImagesProvider` and `ReplicateProvider` on `httpx.MockTransport` (request shape, b64 / poll / download), the refusal / config / outage error classification, and the `IMAGE_PROVIDER` env switch with the fake fallback |
| `test_designs_storage.py` | `LocalStorage` and `S3Storage` behind the `Storage` ABC: `KEY_RE` on put and get (traversal-proof), `new_image_key`, `get_storage` env switch |
| `test_designs_quota.py` | the per-UTC-day quota: count of non-failed rows since midnight, 429 + `Retry-After` to midnight, owner exempt, `AI_DAILY_QUOTA=0` unlimited |
| `test_designs_worker.py` | the generation worker: `FOR UPDATE SKIP LOCKED` claim, outcome per error class (rejected -> failed, transport -> re-queued with backoff, open circuit hands the attempt back), `finished_at` after the provider call, the Personalise hook writing `effective_prompt` |
| `test_designs_api.py` | designs routes on `TestClient` with a `MagicMock` session: route registration, 202 / 404 / 401 / 422, `image_url` only when ready, `/images/{key}` GET + HEAD with immutable caching, saved prompts, quota, style profile |
| `test_designs_summarizer.py` | `deterministic_summary` keyword ranking and `OpenAIChatSummarizer` on `httpx.MockTransport` (4xx degrades to deterministic, 429 / 5xx raise `ProviderError`) |
| `test_designs_print.py` | print-this: the `AI-{id}` / `AI-{id}-{size}` SKU scheme, the seed price ladder, catalog -> inventory -> row orchestration with fake clients, 201 / 200 / 409 / 502 / 503 on the route |
| `test_designs_order_paid.py` | the ORDER_PAID consumer: dedup by event id, `purchased_at` on own SKUs, a `purchases` row per item, profile marked stale, `ON CONFLICT DO NOTHING` on `processed_events`, the `IntegrityError` re-delivery path |
| `test_designs_style_profile.py` | `gather_inputs` (last 20 prompts + deduplicated purchase names), `refresh_profile` keeping the old summary on failure, `ensure_summary` never raising, `compose_effective_prompt` |
| `test_catalog_listed.py` | catalog `products.listed`: `GET /products` hides unlisted families, `GET /products/{sku}` and `/internal/resolve-prices` unchanged (compiled SQL), `POST /internal/products` 201 / 200 / 400 |
| `test_inventory_internal_stock.py` | inventory `POST /internal/stock`: bulk create, existing SKUs skipped, `{created, skipped}` result, service-or-owner guard |
| `test_no_sql_on_event_loop.py` | no sync SQLAlchemy call inside an `async def` in the six services with async DB paths (orders, catalog, designs, logistics, production, inventory) — the static half of the event-loop tripwire (`services/*/database.py` logs the runtime half); one parametrised case per service |
| `test_bulkhead.py` | the per-process bulkhead middleware: admission up to the pool size, queueing, 503 + `Retry-After` after `BULKHEAD_QUEUE_TIMEOUT`, `/healthz`/`/readyz`/`/metrics`/OPTIONS bypass, slot release on exceptions, the limit/timeout env resolution, metrics present at 0, copy drift and innermost registration in the eight DB-backed services |

`designs_testkit.py` is not a test: it is the shared loader that imports the
`services/designs` modules once per pytest process with `database` and `metrics`
stubbed, so every `test_designs_*.py` file runs against the real code without a
database.

## Integration Tests (requires live stack)

Start all services first:
```
make dev
# or: docker compose up -d
```

Then run:
```
pytest tests/integration/ -v
```

`pytest tests/integration -q` runs seven tests across four files:

| File | Covers |
|------|--------|
| `test_order_flow.py` | card order: create -> pay -> past PAID through the outbox -> shipment carries the address copy -> anonymous shipment reads rejected |
| `test_escrow_contract_chain.py` | deploys `services/payments/contracts/OrderEscrow.json` on Ganache from the unlocked account[0] and asserts all nine `require()` strings, the exact 80 % / 20 % payout net of release gas, the refund on cancel and the closed-contract lockout |
| `test_escrow_flow.py` | two tests: an escrow order from create -> deploy -> fund with demo account[1]'s key -> verify -> outbox -> shipped -> courier pick-up with an explicit `courier_wallet` (account[3]) -> delivered -> confirm-delivery, asserting the 80/20 payout on chain; and a funded order that is cancelled and refunds the customer exactly |
| `test_design_flow.py` | three tests: the full studio flow on the fake provider (generate -> ready -> `/images/{key}` is a PNG -> print -> unlisted `AI-{id}` family with four ladder-priced variants -> order `AI-{id}-A3` -> pay -> past PAID through production -> `purchased_at` set by the ORDER_PAID delivery to designs -> style profile refresh counts the purchase -> a `[reject]` prompt fails with the reason); the auth guards on every studio route; the saved-prompts round trip |

The escrow tests need the `ganache` compose service (`docker compose ps ganache`
must be healthy, payments `GET /v1/escrow/config` must report `enabled: true`).
`test_escrow_contract_chain.py` skips when Ganache is unreachable; `test_escrow_flow.py`
fails on purpose, because a stack without escrow is a broken demo stack.

The design flow needs the `designs` compose service on 8010 with `IMAGE_PROVIDER=fake`
(the compose default): a real provider would cost money on every run, and the
`[reject]` hook that drives the refusal step only exists on the fake provider. It
skips nothing either. The flow runs as the self-registered customer
`studio-integration@example.com` (the `studio_http` fixture registers it on the
first run and logs in afterwards); the owner is used only for `/seed` and the
admin-only `POST /orders/{id}/pay`, so the owner's studio history stays clean.
Each run makes one accepted generation (the `[reject]` one fails and does not
count), so the 10/day quota allows ten runs per UTC day, after which the
generation step fails with a 429 message until midnight.

Integration tests seed catalog and inventory via POST /seed before running.
They poll the orders service for up to 30s waiting for status transitions and
drive the courier hand-off themselves (`PUT /shipments/{id}/status`) instead of
waiting for the 120 s auto-advance worker.
