# Project Backlog

Prioritized list of planned improvements and known issues.

See also: [Known Limitations](KNOWN_LIMITATIONS.md) — gaps deliberately kept out of scope for the thesis.

---

## Priority: High

### 1. Refresh Token Implementation
**Status:** Planned  
**Effort:** Medium (2-3 hours)  
**Description:** Implement short-lived access tokens (5-15 min) + long-lived refresh tokens for proper token revocation capability.

**Tasks:**
- [ ] Add `refresh_tokens` table to users schema
- [ ] Modify `create_access_token()` to use shorter expiry
- [ ] Add `create_refresh_token()` function
- [ ] Add `/refresh` endpoint
- [ ] Add `/logout` endpoint to revoke refresh token
- [ ] Update frontend AuthContext with token refresh interceptor
- [ ] Create Alembic migration

**See:** THESIS_SNAPSHOT.md > Security Improvement 1

---

### 2. Event Idempotency
**Status:** Partially done — production: durable (checks for an existing job by order_id); notifications: in-memory set, non-durable  
**Effort:** Low for database-backed consumers (1-2 hours); higher for stateless ones  
**Description:** Add standardized idempotency mechanism for event handlers.

**Tasks:**
- [ ] Add `processed_events` table per **database-backed** consuming service
- [ ] Check event_id before processing
- [ ] Add index on event_id for fast lookups
- [ ] Decide on a mechanism for **stateless** consumers

**Caveat — the proposed fix does not generalize.** A `processed_events` table assumes the
consumer owns a database. `notifications` deliberately does not: it is stateless, with no
schema and no Alembic. Its guard is an in-memory `set` that is per-replica and lost on
restart, so duplicates are possible after a pod restart or with `replicaCount > 1`.
Giving notifications a database purely for idempotency would undo its stateless design.
A shared Redis set with a TTL, or a provider-side idempotency key, fits a stateless
consumer better. This is an architectural choice, not a one-hour task.

---

### 3. Dead Letter Queue
**Status:** Not started  
**Effort:** Medium (2-3 hours)  
**Description:** Events exceeding MAX_RETRIES should go to DLQ instead of being abandoned.

**Stakes raised by the notifications service.** Abandoning an event used to mean a print
job was not queued, which is visible in the production service's own state and
recoverable by an operator looking at order status. Now the same abandonment silently
drops **customer-facing email** — a confirmation or shipping notice that no one will ever
notice is missing, because nothing downstream records that it should have arrived. The
fan-out retry behaviour compounds this: a persistently failing subscriber burns the
shared retry budget for an event other subscribers already handled, and then the whole
event is abandoned.

**Tasks:**
- [ ] Add `dead_letter_events` table in orders schema
- [ ] Move failed events to DLQ after max retries
- [ ] Add `/outbox/dlq` endpoint to view/retry DLQ events
- [ ] Add alerting for DLQ events

---

## Priority: Medium

### 4. Connection Pooling
**Status:** Not started  
**Effort:** Low (1 hour)  
**Description:** Configure SQLAlchemy connection pool settings for better resource efficiency.

**Tasks:**
- [ ] Add pool_size, max_overflow, pool_timeout settings
- [ ] Configure per-service based on expected load
- [ ] Add connection pool metrics

---

### 5. Distributed Tracing
**Status:** Not started  
**Effort:** High (4-6 hours)  
**Description:** Add Jaeger/Zipkin integration for request tracing across services.

**Tasks:**
- [ ] Add OpenTelemetry SDK to services
- [ ] Propagate trace context in HTTP headers
- [ ] Deploy Jaeger to Kubernetes
- [ ] Configure sampling rate

---

### 6. Integration Tests
**Status:** Not started  
**Effort:** High (6-8 hours)  
**Description:** End-to-end tests covering complete order flow.

**Tasks:**
- [ ] Set up test database/docker-compose
- [ ] Test: Create order → Reserve stock → Pay → Produce → Ship → Deliver
- [ ] Test: Order cancellation at various stages
- [ ] Test: Insufficient stock handling
- [ ] Test: Payment failure handling

---

### 7. CI/CD Pipeline
**Status:** Partial (deploy workflow exists)  
**Effort:** Medium (3-4 hours)  
**Description:** Complete CI pipeline with tests and automated deployment.

**Tasks:**
- [ ] Add lint/format checks (ruff, black)
- [ ] Add unit test step
- [ ] Add integration test step
- [ ] Add security scanning
- [ ] Automate version tagging

---

## Priority: Low

### 8. Saga Compensation
**Status:** Not started  
**Effort:** High (4-6 hours)  
**Description:** Add compensation logic for partial failures after stock reserved but before payment.

**Tasks:**
- [ ] Define compensation actions per step
- [ ] Add timeout-based reservation release (partially done with TTL)
- [ ] Add manual intervention endpoint for stuck orders

---

### 9. Async Event Delivery
**Status:** Not started  
**Effort:** Medium (2-3 hours)  
**Description:** Process outbox events in parallel for higher throughput.

**Tasks:**
- [ ] Use asyncio.gather for parallel delivery
- [ ] Add concurrency limit configuration
- [ ] Handle partial failures gracefully

---

### 10. Caching Layer
**Status:** Not started  
**Effort:** Medium (3-4 hours)  
**Description:** Add Redis caching for frequently accessed data.

**Tasks:**
- [ ] Deploy Redis to Kubernetes
- [ ] Cache catalog products (TTL: 5 min)
- [ ] Cache stock levels (TTL: 30s)
- [ ] Add cache invalidation on updates

---

### 11. Multi-AZ Database
**Status:** Not started  
**Effort:** Low (config change)  
**Description:** Enable Multi-AZ for RDS in production.

**Tasks:**
- [ ] Update RDS Terraform/manual config
- [ ] Test failover scenario

---

### 12. Network Policies
**Status:** Not started  
**Effort:** Medium (2-3 hours)  
**Description:** Kubernetes NetworkPolicies to restrict pod-to-pod communication.

**Tasks:**
- [ ] Define allowed ingress/egress per service
- [ ] Test connectivity after applying policies
- [ ] Document network topology

---

## Completed

### ✅ Structured Logging
**Completed:** 2024-01-15  
Added JSON logging with correlation IDs to all services.

### ✅ Centralized Log Aggregation
**Completed:** 2024-01-15  
Deployed Loki + Fluent Bit for log aggregation.

### ✅ Database Migrations
**Completed:** 2024-01-15  
Implemented Alembic migrations for all database-backed services with Kubernetes Job integration.

### ✅ Stock Reservation TTL
**Completed:** Previously implemented  
Reservations automatically expire after 15 minutes (configurable) with background worker.

### ✅ User Accounts for Shop
**Completed:** 2024-01-14  
Added login/register/my-orders functionality to shop frontend.

### ✅ Email Notifications (SES)
**Completed:** 2026-07-05  
Added the `notifications` service — a stateless consumer of the orders outbox that sends
transactional email for `ORDER_PAID`, `ORDER_SHIPPED`, `ORDER_DELIVERED` and
`ORDER_CANCELLED`. Transport is pluggable behind an `EmailProvider` abstraction: a
logging provider for local development and demos (no AWS credentials needed) and an AWS
SES provider for production, authenticated through IRSA so no access key is stored
anywhere. Delivery is instrumented with `notifications_emails_sent_total` and
`notifications_email_send_failures_total`.

The same change made the outbox genuinely publish-subscribe: `ORDER_PAID` and
`ORDER_CANCELLED` now fan out to both production and notifications, and orders gained two
new event types emitted in the same transaction as their status change.

Verified locally with the logging provider only — **SES was not exercised against real
AWS**. Remaining gaps are tracked as items 2 and 3 above and in
`docs/KNOWN_LIMITATIONS.md`.

---

## Ideas (Not Prioritized)

- **CQRS for Orders:** Separate read/write models for order queries
- **Event Sourcing:** Full audit trail with temporal queries
- **Saga Orchestrator:** Centralized saga coordination
- **GraphQL Gateway:** Unified API for frontend
- **Rate Limiting:** Per-user/IP rate limits
- **Feature Flags:** Gradual rollout of features
- **A/B Testing:** Experiment framework
- **Load Testing:** k6/Locust load tests
- **Chaos Engineering:** Failure injection testing

---

## Notes

- Priorities are based on thesis relevance and system stability
- Time estimates are rough guides, not commitments
- Items may be reprioritized based on emerging needs
