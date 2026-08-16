# Known Limitations

Gaps kept out of scope for the thesis implementation but worth surfacing for completeness.

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

**Interaction with email**: cancelling a `paid` order now also sends the customer a cancellation email, while no money is returned. The email wording is deliberately conditional on `previous_status` and `released_stock` (`services/notifications/main.py`, `render_email()`) so it never claims stock was released when it was not, and never asserts any payment outcome — it directs the customer to support instead. The underlying gap is unchanged; only the messaging is prevented from making a false promise.

## 3. Notifications idempotency — RESOLVED (durable `processed_events`)

**Resolved** (quick task 260815-m0m): notifications now owns `notifications_schema` with a `processed_events(event_id PK)` table and dedups durably (`SELECT` by `event_id`, then `INSERT ... ON CONFLICT DO NOTHING` after a successful send). A re-delivered event no longer sends a duplicate email across a pod restart or with `replicaCount > 1` (verified end-to-end incl. a real container restart). The only residual is the narrow send→record crash window — a rare duplicate, deliberately biased over a dropped email, since email is not an idempotent sink. The historical description below is kept for context.

**Symptom (historical)**: A customer could receive a duplicate email for the same order event after a notifications pod restart, or when `replicaCount > 1`.

**Why it persists**: The service is stateless by design and has no database, so the processed-event guard is a Python `set` of `event_id` values held in process memory (`services/notifications/main.py`). Two consequences follow. The set is lost on restart, so an at-least-once redelivery arriving afterwards is treated as new. And the set is per-replica, so with more than one pod each replica has an independent view — a redelivery routed to a different pod is not recognised as a duplicate. The set also grows without bound for the lifetime of the pod, since nothing evicts old IDs.

**Real-world impact**: low — the blast radius of a duplicate transactional email is a mildly confused customer, and redelivery only occurs when a subscriber failed. Unbounded growth is bounded in practice by pod lifetime and the small size of an integer set.

**Fix shape**: the standard remedy (a `processed_events` table per consumer, as proposed in `docs/BACKLOG.md`) does not apply here without giving notifications a database and undoing its stateless design. A shared Redis set with a TTL, or an idempotency key honoured by the email provider itself, fits better. Either is a genuine architectural change rather than a patch.

## 4. Outbox retry is per-event, not per-subscriber

**Symptom**: When one subscriber to a fanned-out event fails, subscribers that already succeeded receive the event again on retry.

**Why it persists**: `ORDER_PAID` and `ORDER_CANCELLED` each fan out to both production and notifications, but the outbox row is the unit of delivery tracking (`services/orders/outbox.py`). There is one `delivered_at` per event, not one per subscriber, so the worker can only mark the whole event delivered once every subscriber has succeeded. If notifications returns `503` while production already returned `200`, the retry re-posts to both.

**Real-world impact**: moderate — it is the direct reason every consumer must be idempotent, and it is why the notifications idempotency gap above matters more than it otherwise would. It also means a single persistently failing subscriber can exhaust the retry budget for an event that other subscribers handled correctly, after which the event is abandoned entirely (there is no dead letter queue).

**Fix shape**: per-subscriber delivery tracking — either a join table of (event_id, subscriber_url, delivered_at), or one outbox row fanned out at write time. The first preserves the single-write-per-business-event property of the outbox pattern and is the more faithful fix.

## 5. CI redeploy of `notifications` silently reverts SES to `logging`

`EMAIL_PROVIDER=ses` is chosen by detection logic in `deploy/full-deploy.sh`
(a verified SES identity plus an IRSA-annotated ServiceAccount), and applied with
`--set email.*`. `.github/workflows/deploy.yaml` has no equivalent, so any push
touching `services/notifications/**` redeploys the chart with its default
`email.provider: logging`, and real mail silently stops.

**Why it persists:** the same shape as the `CORS_ORIGINS` patch — settings applied
outside Helm's own values are invisible to a later `helm upgrade` driven by CI.

**Fix when needed:** either teach `deploy.yaml` the same detection, or commit the
values into the chart so they are not environment-derived.

## 6. Default owner credential is reachable from the internet

`services/users/init_db.py` seeds `admin@postershop.com` / `admin1234` whenever no
owner exists. With the platform deployed behind a public ALB that account is
internet-reachable with owner rights over catalog, inventory, orders and the infra
service (which can scale and restart Deployments).

**Accepted for a thesis demo cluster that is torn down between sessions.** Change
the password or restrict the ingress before leaving a cluster running.

