# Known Limitations

Two gaps in the order lifecycle, kept out of scope for the thesis implementation but worth surfacing for completeness.

## 1. Orphan `created` orders never auto-cancel

**Symptom**: An order that gets stuck in `created` state (e.g. orders service crash mid-reservation) stays there indefinitely.

**Why it persists**: The state machine transitions `created → reserved` happen inside the `create_order` handler synchronously. If the process is interrupted between the row insert and the inventory call, the order is left in `created` with no claim on inventory. The only existing auto-cancel paths are Stripe checkout expiry (requires the customer to have started checkout) and manual cancellation by the customer/owner.

**Real-world impact**: minor — `created` is normally a sub-second intermediate state. Mostly relevant to operational hygiene (stale rows in the orders table).

**Fix shape**: Background worker in orders service polling every minute for orders in `created` status older than ~10 minutes, marking them `cancelled` and emitting the `ORDER_CANCELLED` outbox event. ~20 lines following the existing reservation-expiry worker pattern.

## 2. Cancelling a `paid` order does not release committed stock or refund

**Symptom**: A customer or owner cancels an order that has reached `paid` status. The order moves to `cancelled`, but the inventory stock committed at payment time stays committed, and no refund is issued to the customer's card.

**Why it persists**: The `cancel_order` handler at `services/orders/main.py:425-478` only calls `inventory.release_stock()` when the prior status was `reserved` (line 448). For `paid` orders, stock was already moved from `reserved → committed` via `inventory.commit_stock()` in the Stripe webhook handler — there is no symmetric `return_committed_stock` endpoint on inventory. No Stripe Refund API call is made either.

**Real-world impact**: significant for a real shop — stock is "lost" until manual reconciliation, and the customer's money sits with Stripe with no automatic refund. Production e-commerce platforms typically handle this with a combination of: (a) an inventory rollback endpoint, (b) a Stripe Refund API call, (c) an event-driven saga that compensates each step. All three are deferred here as out-of-scope.

**Fix shape**: ~1-2 hours of work touching 3 services — new inventory `POST /return` endpoint that increments `available` for the SKUs in the order, `cancel_order` calls it when prior status was `paid`, plus a `stripe.Refund.create(payment_intent=order.payment_intent_id)` call. Idempotency keyed by order_id.
