<!-- GSD:project-start source:PROJECT.md -->
## Project

**PosterShop Platform**

A microservices-based e-commerce platform for selling custom posters, deployed on AWS EKS. Built as a diploma thesis project demonstrating distributed systems patterns: event-driven architecture (transactional outbox), service coordination, autoscaling, monitoring, and production-grade operational practices. The platform includes both a customer-facing shop and an admin dashboard for infrastructure management.

**Core Value:** A fully functional, production-worthy poster shop that demonstrates real-world microservices patterns without over-engineering — good enough to deploy, defend in a thesis, and be proud of.

### Constraints

- **Timeline**: Implementation complete by mid-May 2026 — thesis writing needs 1-2 weeks after
- **Budget**: Minimize AWS costs — cluster should be tear-down-able when not actively testing
- **Tech stack**: Python/FastAPI backend, React frontend, PostgreSQL, AWS EKS — no stack changes
- **Complexity**: Production-worthy but not over-engineered. Every addition must justify its thesis value.
- **Testing**: Basic confidence tests, not full coverage. Enough to catch major breaks before deploy.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.11 - All backend microservices (9 services), runtime specified in `services/payments/Dockerfile` as `python:3.11-slim`
- TypeScript/JavaScript (ES Modules) - Frontend application in `frontend/`
- SQL - Database migrations via Alembic, init scripts in `db/init.sql`
- YAML - Kubernetes manifests, Helm charts, GitHub Actions workflows
- Bash - Deployment scripts in `deploy/`
## Runtime
- Python 3.11 (slim Docker images) - Backend services
- Node.js 20 (Alpine Docker image) - Frontend build stage (`frontend/Dockerfile`)
- Nginx (Alpine) - Frontend production serving
- pip - Python dependencies via `requirements.txt` per service
- npm - Frontend dependencies via `package.json` with `npm ci` in Docker builds
- Lockfile: `package-lock.json` present for frontend; no `pip` lockfiles (pinned versions vary by service)
## Frameworks
- FastAPI - All 8 backend microservices, REST API framework
- Uvicorn - ASGI server for all Python services
- React 19.2 - Frontend SPA (`frontend/package.json`)
- Vite 5.4 - Frontend build tool and dev server
- SQLAlchemy 2.0+ - ORM for all database-backed services (users, catalog, orders, production, logistics, inventory)
- Alembic >= 1.13.0 - Database migrations for all database-backed services
- psycopg2-binary - PostgreSQL driver
- Not detected - No test framework configured in any service
- Docker / Docker Compose - Local development and container builds (`docker-compose.yaml`)
- Make - Build automation (`Makefile`)
- Helm 3.13 - Kubernetes package management (`deploy/charts/`)
- eksctl - EKS cluster management
## Key Dependencies
| Dependency | Version | Purpose | Risk Level |
|-----------|---------|---------|------------|
| FastAPI | 0.100-0.119 (varies) | REST API framework for all services | Medium - version inconsistency across services |
| SQLAlchemy | >=2.0 | ORM and database access | Low |
| Pydantic | >=2.0 (varies) | Request/response validation | Low |
| React | ^19.2.0 | Frontend UI library | Low |
| react-router-dom | ^7.11.0 | Client-side routing | Low |
| @tanstack/react-query | ^5.90.12 | Server state management, data fetching | Low |
| Dependency | Version | Purpose | Risk Level |
|-----------|---------|---------|------------|
| psycopg2-binary | >=2.9 | PostgreSQL driver | Low |
| Alembic | >=1.13.0 | Database schema migrations | Low |
| prometheus-client | >=0.15.0, newest pin 0.23.1 | Metrics exposition for Prometheus scraping | Low |
| httpx | >=0.25.0 | Async HTTP client for inter-service calls | Low |
| python-jose | 3.5.0 | JWT token creation/validation (users, catalog, logistics) | Medium - unmaintained library |
| passlib | 1.7.4 | Password hashing (users service) | Medium - unmaintained |
| boto3 | 1.38.0 | AWS SDK (catalog, logistics, notifications services) | Low - pinned |
| kubernetes | unpinned | K8s Python client (infra service) | Low |
| websockets | unpinned | WebSocket support (infra service) | Low |
| Tailwind CSS | ^3.4.19 | Utility-first CSS framework (frontend) | Low |
| lucide-react | ^0.562.0 | Icon library (frontend) | Low |
| clsx | ^2.1.1 | Conditional CSS class utility (frontend) | Low |
| Dependency | Version | Purpose | Risk Level |
|-----------|---------|---------|------------|
| ESLint | ^9.39.1 | JavaScript/TypeScript linting | Low |
| PostCSS | ^8.5.6 | CSS processing (Tailwind) | Low |
| autoprefixer | ^10.4.23 | CSS vendor prefixing | Low |
| @vitejs/plugin-react | ^4.7.0 | React support for Vite | Low |
## Configuration
- Each service configured via environment variables (DATABASE_URL, JWT_SECRET, service URLs)
- `env.example` documents all required variables
- Docker Compose sets env vars per service in `docker-compose.yaml`
- Production secrets managed via AWS Secrets Manager + ExternalSecrets operator (`deploy/secrets/external-secrets.yaml`)
- `.env` file loaded by Makefile when present
- `Makefile` - Primary build/deploy automation (root level)
- `docker-compose.yaml` - Local multi-service orchestration
- `frontend/Dockerfile` - Multi-stage build (Node builder + Nginx production)
- `services/*/Dockerfile` - Python 3.11-slim based service images
- `.github/workflows/build-and-push.yaml` - CI build pipeline
- `.github/workflows/deploy.yaml` - CD deployment pipeline
## Platform Requirements
- Docker and Docker Compose
- Make
- Python 3.11+ (if running services locally outside Docker)
- Node.js 20+ (if running frontend locally outside Docker)
- AWS EKS (Kubernetes 1.32) - `cluster.yaml`, `deploy/infrastructure/eksctl-cluster.yaml`
- AWS RDS PostgreSQL - `deploy/infrastructure/rds.yaml` (CloudFormation)
- AWS ECR - Container image registry
- AWS Secrets Manager - Secret storage with ExternalSecrets operator
- AWS ALB Ingress Controller - Frontend ingress (`deploy/charts/frontend/templates/ingress.yaml`)
- Helm 3 - Deployment packaging (`deploy/charts/`)
- Prometheus + Grafana - Monitoring stack (`deploy/monitoring/prometheus-values.yaml`)
- Fluent Bit + Loki - Log aggregation (`deploy/monitoring/fluent-bit-values.yaml`, `deploy/monitoring/loki-values.yaml`)
- GitHub Actions with OIDC - CI/CD (`.github/workflows/`)
## Service Architecture Overview
| Service | Port (local) | Database | Key Dependencies |
|---------|-------------|----------|-----------------|
| users | 8001 | PostgreSQL (users schema) | python-jose, passlib |
| catalog | 8002 | PostgreSQL (catalog schema) | boto3, httpx |
| orders | 8003 | PostgreSQL (orders schema) | httpx (inventory, payment clients) |
| production | 8004 | PostgreSQL (production schema) | httpx |
| logistics | 8005 | PostgreSQL (logistics schema) | boto3, python-jose, httpx |
| inventory | 8006 | PostgreSQL (inventory schema) | - |
| payments | 8007 | None (in-memory mock) | httpx |
| infra | 8008 | None | kubernetes, websockets |
| notifications | 8009 | None (stateless) | boto3 (SES) |
| frontend | 3000 | None | React, Vite, Nginx |
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Conventions
- **Files:** `snake_case.py` for Python, `PascalCase.jsx` for React components
- **Functions/Methods:** `snake_case` (Python), `camelCase` (JavaScript)
- **Variables:** `snake_case` (Python), `camelCase` (JavaScript)
- **Types/Classes:** `PascalCase` in both Python and JavaScript
- **Constants:** `UPPER_SNAKE_CASE` (Python)
- **DB Schemas:** `<service_name>` or `<service_name>_schema` (e.g., `orders_schema`, `users`)
- **DB Tables:** `plural_snake_case` (e.g., `orders`, `order_items`, `outbox_events`)
## Code Organization Patterns
- `main.py` — FastAPI app, route handlers, lifespan management
- `models.py` — SQLAlchemy ORM models
- `schemas.py` — Pydantic request/response schemas
- `database.py` — Engine, session factory, `get_db()` dependency
- `metrics.py` — Prometheus counters/histograms + middleware
- `logger.py` — Structured JSON logging (copied from `shared/logger.py`)
- `alembic/` — Database migration scripts
- `requirements.txt` — Python dependencies
## Error Handling
- **HTTP errors:** `raise HTTPException(status_code=..., detail=...)` directly in route handlers
- **Service-to-service:** Custom exception classes (e.g., `InsufficientStockError`, `SkuNotFoundError`, `PaymentServiceError`)
- **HTTP clients:** `httpx` with try/except, raising custom errors on failure
- **Database:** SQLAlchemy exceptions caught and re-raised as HTTPException
## Logging
- **Library:** Custom structured JSON logger (`services/shared/logger.py`)
- **Format:** JSON output for Loki/Fluent Bit ingestion
- **Features:** Correlation ID propagation (via `X-Correlation-ID` header), request context middleware
- **Usage:** `logger = get_logger(__name__)` then `logger.info("message", key=value)`
- **Middleware:** `LoggingMiddleware` added to every FastAPI app for request logging with timing
## Configuration Management
- **Environment variables:** All config via `os.getenv()` with defaults
- **Database URLs:** `DATABASE_URL` env var per service
- **Service discovery:** `<SERVICE>_SERVICE_URL` env vars (e.g., `INVENTORY_SERVICE_URL`)
- **Secrets:** JWT_SECRET, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET via env vars. Notifications needs no secret — its AWS SES access comes from an IAM role assumed via IRSA, so no key is stored
- **Local dev:** `.env` file loaded by docker-compose and Makefile
- **Production:** AWS Secrets Manager → External Secrets Operator → Kubernetes Secrets
## API Conventions
- **Framework:** FastAPI with auto-generated OpenAPI docs at `/docs`
- **Health check:** `GET /healthz` on every service
- **Metrics:** `GET /metrics` — Prometheus-format metrics
- **Seed data:** `POST /seed` — populate with sample data (catalog, inventory)
- **Request/Response:** Pydantic models for validation; JSON throughout
- **Auth:** JWT Bearer tokens via `Authorization: Bearer <token>` header
- **Inter-service:** Synchronous HTTP via `httpx` client; async events via outbox pattern
- **Event endpoints:** `POST /events/<event-type>` for consuming outbox events
## Database Patterns
- **ORM:** SQLAlchemy 2.0 with declarative base
- **Sessions:** Sync sessions via `SessionLocal()` with FastAPI `Depends(get_db)`
- **Migrations:** Alembic per service (each service owns its schema)
- **Schema isolation:** Each service uses its own PostgreSQL schema (e.g., `orders_schema`, `users`)
- **Connection:** `create_engine(DATABASE_URL, pool_pre_ping=True)`
- **Indexes:** Explicit indexes on frequently queried columns
- **State machine:** Order status transitions defined as class constants with validation
## Git Conventions
- **Branch:** Work on `master` branch
- **Commit style:** Lowercase, descriptive messages (e.g., "docs, deploy scripts, initial and services migrations, a bunch of updates")
- **CI/CD:** A push to `master` touching `services/**` or `frontend/**` builds the changed services, pushes them to ECR, and helm-upgrades them into the `postershop` namespace (`.github/workflows/build-and-push.yaml` → `.github/workflows/deploy.yaml`). `make` targets and `deploy/full-deploy.sh` remain the local and bootstrap path.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- 9 independent Python/FastAPI backend services; the six database-backed ones each own their own PostgreSQL schema, while payments, infra and notifications are stateless
- Single React SPA frontend acting as both admin dashboard and customer-facing shop
- Synchronous HTTP inter-service communication via `httpx` async clients
- Asynchronous event delivery via the Outbox Pattern, fanning out to multiple subscribers (orders -> production, notifications)
- Nginx reverse proxy (in production Docker) routing `/api/{service}/` to backend services
- Each service runs on port 8000 internally, exposed on unique host ports (8001-8009)
## Layers
- Purpose: Admin dashboard and customer-facing poster shop
- Location: `frontend/src/`
- Contains: React components, pages, context providers, API client
- Depends on: All backend services via `/api/{service}/` proxy routes
- Used by: End users (customers and admins)
- Purpose: Routes `/api/{service}/` paths to backend services, serves static frontend
- Location: `frontend/nginx.conf` (production), `frontend/vite.config.js` (dev proxy)
- Contains: Proxy rules, gzip config, security headers
- Depends on: All backend services
- Used by: Frontend SPA
- Purpose: Domain-specific business logic, each a standalone FastAPI application
- Location: `services/{service_name}/main.py`
- Contains: REST endpoints, SQLAlchemy models, Pydantic schemas, background workers
- Depends on: PostgreSQL (via SQLAlchemy), other services (via HTTP clients)
- Used by: Frontend via Nginx proxy, other services via direct HTTP
- Purpose: Persistent storage with schema-per-service isolation
- Location: `db/init.sql` (schema/user setup), `services/{service}/alembic/` (migrations)
- Contains: PostgreSQL schemas: `users`, `catalog`, `orders`, `production`, `logistics`, `inventory`
- Depends on: Single PostgreSQL 16 instance
- Used by: All services with database needs (all except payments, infra and notifications)
- Purpose: Kubernetes (EKS) deployment with Helm charts
- Location: `deploy/`
- Contains: Helm charts per service, infrastructure scripts, monitoring config
- Depends on: AWS (EKS, ECR, RDS), Helm, eksctl
- Used by: CI/CD pipeline and `make` commands
## Data Flow
```
```
- Server-side: Each service owns its state in its PostgreSQL schema
- Frontend: React Query for server state (5s refetch interval), React Context for auth and cart
- Payments service uses in-memory storage (sessions dict) -- not persistent
## Key Abstractions
- Purpose: Typed async HTTP clients for inter-service calls
- Examples: `services/orders/inventory_client.py`, `services/orders/payment_client.py`, `services/production/orders_client.py`, `services/logistics/orders_client.py`
- Pattern: Each client module defines a base URL from env vars, custom exception classes, and async functions using `httpx.AsyncClient`
- Purpose: Reliable at-least-once event delivery between services
- Examples: `services/orders/outbox.py`
- Pattern: Events written to `outbox_events` table in same transaction as business logic. Background worker polls and delivers via HTTP POST to subscriber URLs. Exponential backoff retry (5s, 15s, 1m, 5m, 15m). Max 5 retries. Multi-subscriber fan-out: `EVENT_SUBSCRIBERS` maps 4 event types to 6 URLs — `ORDER_PAID` and `ORDER_CANCELLED` go to both production and notifications, `ORDER_SHIPPED` and `ORDER_DELIVERED` to notifications only. Retry is per-event, not per-subscriber, so a failure at one subscriber re-delivers to those that already succeeded.
- Purpose: Swappable email transport so local development needs no AWS credentials
- Examples: `services/notifications/providers.py` (`EmailProvider` ABC, `LoggingProvider`, `SesProvider`)
- Pattern: Abstract base class with a single `send(to, subject, body)` method, selected at startup by the `EMAIL_PROVIDER` env var (`get_provider()`). LoggingProvider renders into the structured log for docker-compose and demos; SesProvider calls AWS SES via boto3 with credentials from IRSA rather than any stored key.
- Purpose: Enforces valid order status transitions
- Examples: `services/orders/models.py` (`OrderStatus` class)
- Pattern: Explicit transition map: CREATED -> RESERVED -> PAID -> PRODUCING -> SHIPPED -> DELIVERED. Terminal states: CANCELLED, FAILED, DELIVERED.
- Purpose: Each service gets its own PostgreSQL schema within a shared database
- Examples: `db/init.sql`, each service's `DATABASE_URL` uses `?options=-csearch_path%3D{schema}`
- Pattern: Separate DB users per service with grants only on their schema. Alembic manages migrations per service.
- Purpose: Consistent JSON log format across all services with correlation ID propagation
- Examples: `services/shared/logger.py` (canonical copy), copied to each service as `logger.py`
- Pattern: `LoggingMiddleware` extracts/generates `X-Correlation-ID`, `StructuredLogger` adapter supports kwargs-based structured fields
## Entry Points
- Location: `frontend/src/main.jsx` -> `frontend/src/App.jsx`
- Triggers: Browser navigation
- Responsibilities: Renders admin dashboard (/) and customer shop (/shop) routes
- Location: `services/{service}/main.py`
- Triggers: HTTP requests (FastAPI/Uvicorn on port 8000)
- Responsibilities: REST API endpoints, background workers (outbox, job processing, reservation expiry)
- Location: `docker-compose.yaml`
- Triggers: `make dev` / `docker compose up`
- Responsibilities: Orchestrates all services + PostgreSQL locally
- Location: `deploy/charts/{service}/`
- Triggers: `make deploy-services` / CI pipeline
- Responsibilities: Kubernetes Deployment + Service manifests per service
## Error Handling
- Services raise `HTTPException` with specific status codes (400, 404, 409, 503)
- Inter-service clients define typed exceptions: `InsufficientStockError`, `SkuNotFoundError`, `InventoryServiceError`, `PaymentServiceError`
- Saga-like compensation: Order creation reserves stock item by item; on failure, releases previously reserved items (best-effort)
- Outbox pattern retries failed event deliveries with exponential backoff
- Background workers catch all exceptions to prevent task cancellation
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
