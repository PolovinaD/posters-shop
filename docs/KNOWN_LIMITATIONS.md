# Known Limitations

Gaps kept out of scope for the thesis implementation but worth surfacing for completeness.

## 1. Orphan `created` orders never auto-cancel

**Symptom**: An order that gets stuck in `created` state (e.g. orders service crash mid-reservation) stays there indefinitely.

**Why it persists**: The state machine transitions `created → reserved` happen inside the `create_order` handler synchronously. If the process is interrupted between the row insert and the inventory call, the order is left in `created` with no claim on inventory. The only existing auto-cancel paths are Stripe checkout expiry (requires the customer to have started checkout) and manual cancellation by the customer/owner.

**Real-world impact**: minor — `created` is normally a sub-second intermediate state. Mostly relevant to operational hygiene (stale rows in the orders table).

**Fix shape**: Background worker in orders service polling every minute for orders in `created` status older than ~10 minutes, marking them `cancelled` and emitting the `ORDER_CANCELLED` outbox event. ~20 lines following the existing reservation-expiry worker pattern.

## 2. Cancelling a `paid` order does not release committed stock or refund

**Symptom**: A customer or owner cancels an order that has reached `paid` status. The order moves to `cancelled`, but the inventory stock committed at payment time stays committed, and no refund is issued to the customer's card.

**Why it persists**: The `cancel_order` handler at `services/orders/main.py:500-560` only calls `inventory.release_stock()` when the prior status was `reserved` (line 529). For `paid` orders, stock was already moved from `reserved → committed` via `inventory.commit_stock()` in the Stripe webhook handler — there is no symmetric `return_committed_stock` endpoint on inventory. No Stripe Refund API call is made either.

**Real-world impact**: significant for a real shop — stock is "lost" until manual reconciliation, and the customer's money sits with Stripe with no automatic refund. Production e-commerce platforms typically handle this with a combination of: (a) an inventory rollback endpoint, (b) a Stripe Refund API call, (c) an event-driven saga that compensates each step. All three are deferred here as out-of-scope.

**Fix shape**: ~1-2 hours of work touching 3 services — new inventory `POST /return` endpoint that increments `available` for the SKUs in the order, `cancel_order` calls it when prior status was `paid`, plus a `stripe.Refund.create(payment_intent=order.payment_intent_id)` call. Idempotency keyed by order_id.

**Interaction with email**: cancelling a `paid` order now also sends the customer a cancellation email, while no money is returned. The email wording is deliberately conditional on `previous_status` and `released_stock` (`services/notifications/main.py`, `render_email()`) so it never claims stock was released when it was not, and never asserts any payment outcome — it directs the customer to support instead. The underlying gap is unchanged; only the messaging is prevented from making a false promise.

That conditional wording only became *effective* in `40d8486`. Before it, the branch could not fire at all: `cancel_order` built the event payload after setting the status, so `previous_status` was always `"cancelled"`, and `notifications` compared the field against uppercase values while `OrderStatus` emits lowercase. Two independent bugs on one field, either sufficient on its own — so a customer whose paid order was cancelled received an email that never mentioned the payment, for as long as the feature had existed.

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

## 5. CI redeploy reverting out-of-chart runtime config — RESOLVED (live-derived Helm values)

**Resolved** (quick task 260817): both `deploy/deploy.sh` and
`.github/workflows/deploy.yaml` now call `build_helm_config_args` from the shared
`deploy/lib/live-config.sh` before every `helm upgrade`. The helper resolves each
out-of-chart setting with the precedence **explicit environment > live cluster >
chart default** and returns the matching `--set` flags, so a CI deploy that knows
nothing about SES or about the ALB hands the running configuration back to Helm
instead of resetting it. Helm remains the owner of the value; nothing is
re-patched after the upgrade, and `--reuse-values` is still not used. A service
that is not part of a deploy is not touched at all. Proven offline by
`deploy/lib/selftest.sh` (cases CFG-1..11, in particular CFG-6, which
reconstructs the whole SES configuration from a live deployment with no
environment hints).

**Symptom (historical)**: `EMAIL_PROVIDER=ses` is chosen by detection logic in
`deploy/full-deploy.sh` (a verified SES identity plus an IRSA-annotated
ServiceAccount), and applied with `--set email.*`. `.github/workflows/deploy.yaml`
had no equivalent, so any push touching `services/notifications/**` redeployed the
chart with its default `email.provider: logging`, and real mail silently stopped.

**Second instance of the same class**: `payments.FRONTEND_URL` — the address a
customer's browser returns to after Stripe checkout. It was patched onto the
Deployment with `kubectl set env` after the ALB appeared, so CI reverted it; and
because the reverted-to value had been hardcoded into
`deploy/charts/payments/values.yaml` (commit `afbc972`), what CI restored was an
ALB hostname belonging to a cluster that no longer existed. Paying customers were
redirected to nothing. Fixed the same way: the chart now carries an empty
`frontendUrl` scalar and the deploy path fills it from the live `frontend`
ingress, which also makes a re-created ALB self-heal on the next deploy.

**Why it happened:** the same shape as the `CORS_ORIGINS` patch — settings applied
outside Helm's own values are invisible to a later `helm upgrade` driven by CI.
See limitation 7 for what is left of that shape.

## 6. Default owner credential is reachable from the internet

`services/users/init_db.py` seeds `admin@postershop.com` / `admin1234` whenever no
owner exists. With the platform deployed behind a public ALB that account is
internet-reachable with owner rights over catalog, inventory, orders and the infra
service (which can scale and restart Deployments).

**Accepted for a thesis demo cluster that is torn down between sessions.** Change
the password or restrict the ingress before leaving a cluster running.

## 7. Residual out-of-chart config, and the durable fix for the Stripe return URL

Limitation 5 is resolved for the two settings that were actually breaking. Three
related things were deliberately left alone.

**(a) `CORS_ORIGINS` is still applied outside Helm.** `deploy/deploy.sh` patches it
onto every Deployment with `kubectl set env` after the upgrade, so a CI deploy
still reverts it to the chart default `http://localhost:3000`. This is the same
class of bug as limitation 5, but it is *latent* rather than bleeding: in
production the browser reaches every service same-origin through the frontend
nginx proxy (`frontend/nginx.conf` routes `/api/{service}/`), so no cross-origin
request is made and the wrong value is never consulted. Fixing it properly means
adding a scalar to nine charts and rendering it in nine Deployment templates —
a large, entirely mechanical change with no observable effect today, so it was
not bundled with a fix for something that was actively broken.

**(b) The durable fix for the Stripe return URL is caller-supplied URLs, not a
server-side `FRONTEND_URL` at all.** `services/payments/main.py` already accepts
`success_url` and `cancel_url` on `CreateSessionRequest` and prefers them when
supplied; `services/orders/main.py` does not send them today. Having orders pass
through the origin the customer is actually browsing removes the server-side
guess entirely — it cannot go stale, and it is correct even with several
front-ends. It was deferred because it touches frontend, orders and payments at
once and can only be *proven* by a real Stripe checkout against a live cluster.
The live-derived `frontendUrl` is the cheap, testable fix for the same symptom.

**(c) Chart-only changes do not auto-deploy.** The build workflow's `paths:`
filter is `services/**` and `frontend/**` (`docs/BACKLOG.md` §7b, a deliberate
limitation), so the payments chart change described in limitation 5 reaches the
cluster only on the next deploy that includes `payments` — a push touching
`services/payments/**`, a manual **Deploy to EKS** `workflow_dispatch`, or a
`deploy/deploy.sh` run. Until then the live Deployment keeps whatever
`FRONTEND_URL` it currently has.

## 8. Reservation TTL can cancel an order the customer has already paid for

**Symptom**: A customer who spends more than 15 minutes on Stripe Hosted Checkout completes the payment and then finds the order `cancelled`. The money has left their card and the platform holds no order for it.

**Why it persists**: The reservation TTL is hardcoded at `services/orders/main.py:184` (`ttl_minutes=15`, matching the inventory-side default at `services/inventory/schemas.py:33`) and starts ticking when stock is reserved inside `create_order` — before the customer has been redirected to Stripe at all, and regardless of how long they then spend there. Inventory's expiry worker polls every 30 seconds (`services/inventory/main.py:124`), releases each expired reservation and posts to `POST /internal/orders/{order_id}/reservation-expired` (`services/inventory/main.py:52` → `services/orders/main.py:729`), which flips an order still sitting in `reserved` to `cancelled` and emits `ORDER_CANCELLED`. Nothing along that path knows whether a Stripe checkout session is open: `create_checkout` (`services/orders/main.py:565`) records `checkout_session_id` on the order but does not touch the reservation's `expires_at`, and the expiry worker never consults it. Hosted Checkout is off-platform and takes as long as the customer takes, so the two clocks are simply unrelated and the slower customer loses the race.

**Real-world impact**: significant for a real shop — this is the one failure mode here that takes a customer's money. Observed on the live cluster: order 5 was created at 22:50:36 and cancelled at 23:05:40, exactly the TTL, after the customer had already paid. The payment is captured at Stripe, no order survives to be fulfilled, and no refund is issued, because no refund path exists anywhere in the platform — see limitation 2 for the same missing `stripe.Refund.create` call on the manual cancellation route. Unlike limitation 2, the stock itself is fine: the order was still `reserved`, so inventory released it correctly on the way through.

**Fix shape**: make the reservation follow the checkout session rather than a fixed wall clock — a new inventory endpoint that extends a reservation's `expires_at`, called from `create_checkout` when the session is opened (and again on session refresh), so stock is released only once Stripe itself expires the session. ~1 hour touching orders and inventory, with the reservation-expired callback left exactly as it is. Pausing the TTL outright is the simpler variant but needs an explicit release on the Stripe `checkout.session.expired` event to avoid leaking stock.

## 9. Circuit-breaker failure threshold is per process, not per platform

**Symptom**: `CB_FAILURE_THRESHOLD` does not describe the number of failed downstream calls the platform actually tolerates. With orders running more than one pod, a broken dependency absorbs several times that many calls before any circuit opens.

**Why it persists**: `services/orders/circuit_breaker.py:95` opens the circuit on `self._failure_count >= self.failure_threshold`, and `_failure_count` is plain in-process instance state on the `CircuitBreaker` object (initialised at `services/orders/circuit_breaker.py:57`). Nothing is shared between pods, so each replica keeps its own counter and runs its own independent state machine. The threshold defaults to 5 (`services/orders/inventory_client.py:18`, `services/orders/payment_client.py:20`; `recovery_timeout` 30 s) while orders runs 2-5 replicas under its HPA (`deploy/charts/orders/templates/hpa.yaml`), and the Kubernetes Service spreads requests across all of them — so every pod has to accumulate its own five failures, and the effective platform-wide threshold is 5 × the current replica count.

**Real-world impact**: moderate — measured live with two replicas, the first pod opened its circuit on the 9th attempt and the second on the 14th, not the 5th the setting implies. The perverse consequence is that the protection weakens exactly when it is most needed: scaling out under load multiplies the number of failed calls the platform will send at an already-failing dependency, reaching 25 at the HPA ceiling of 5 replicas. That is the opposite of what a reader of the setting assumes. It is the same shape as the per-replica in-memory idempotency set described in limitation 3 — per-process state standing in for shared state — which is why that one had to be given a durable store rather than a bigger set.

**Fix shape**: shared breaker state. Either a Redis-backed failure counter keyed by dependency that every replica increments and reads, keeping `circuit_breaker.py`'s state machine but moving its two fields out of the process; or a service mesh that owns outlier detection outside the application entirely. Both are infrastructure additions rather than patches, which is why the per-process version ships as-is with the multiplier documented here.

