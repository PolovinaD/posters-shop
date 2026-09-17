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

`pytest tests/integration -q` runs four tests across three files:

| File | Covers |
|------|--------|
| `test_order_flow.py` | card order: create -> pay -> past PAID through the outbox -> shipment carries the address copy -> anonymous shipment reads rejected |
| `test_escrow_contract_chain.py` | deploys `services/payments/contracts/OrderEscrow.json` on Ganache from the unlocked account[0] and asserts all nine `require()` strings, the exact 80 % / 20 % payout net of release gas, the refund on cancel and the closed-contract lockout |
| `test_escrow_flow.py` | two tests: an escrow order from create -> deploy -> fund with demo account[1]'s key -> verify -> outbox -> shipped -> courier pick-up with an explicit `courier_wallet` (account[3]) -> delivered -> confirm-delivery, asserting the 80/20 payout on chain; and a funded order that is cancelled and refunds the customer exactly |

The escrow tests need the `ganache` compose service (`docker compose ps ganache`
must be healthy, payments `GET /v1/escrow/config` must report `enabled: true`).
`test_escrow_contract_chain.py` skips when Ganache is unreachable; `test_escrow_flow.py`
fails on purpose, because a stack without escrow is a broken demo stack.

Integration tests seed catalog and inventory via POST /seed before running.
They poll the orders service for up to 30s waiting for status transitions and
drive the courier hand-off themselves (`PUT /shipments/{id}/status`) instead of
waiting for the 120 s auto-advance worker.
