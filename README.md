# PosterShop Platform

A microservices-based e-commerce platform for art prints, deployed on AWS EKS.

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │        AWS Application Load Balancer │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────┴───────────────────┐
                    │           Kubernetes (EKS)          │
                    │                                     │
    ┌───────────────┼─────────────────────────────────────┼───────────────┐
    │               │                                     │               │
┌───┴───┐     ┌─────┴─────┐     ┌─────────┐     ┌────────┴────────┐     │
│Frontend│    │   users   │     │ catalog │     │    inventory    │     │
│ (React)│    │  (auth)   │     │(products│     │ (stock/reserve) │     │
└───────┘     └───────────┘     └─────────┘     └─────────────────┘     │
                    │                                     │               │
              ┌─────┴─────┐     ┌─────────┐     ┌────────┴────────┐     │
              │  orders   │────▶│production│    │    logistics    │     │
              │(lifecycle)│     │ (jobs)  │     │  (shipments)    │     │
              └───────────┘     └─────────┘     └─────────────────┘     │
                    │                                                    │
              ┌─────┴─────┐     ┌─────────┐     ┌─────────────────┐     │
              │ payments  │     │  infra  │     │  notifications  │     │
              │ (Stripe)  │     │ (k8s)   │     │  (email/SES)    │     │
              └───────────┘     └─────────┘     └─────────────────┘     │
    └───────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┴───────────────────┐
                    │         RDS PostgreSQL              │
                    │   (schema-per-service isolation)    │
                    └─────────────────────────────────────┘
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| **users** | 8000 | JWT authentication, user registration, role management |
| **catalog** | 8000 | Products, categories, sizes, frames |
| **inventory** | 8000 | Stock levels, reservations, commits |
| **orders** | 8000 | Order lifecycle, outbox event emission |
| **production** | 8000 | Print job management (event-driven) |
| **logistics** | 8000 | Shipment tracking |
| **payments** | 8000 | Real Stripe Hosted Checkout sessions |
| **infra** | 8000 | Kubernetes cluster introspection API |
| **notifications** | 8000 | Transactional email on order events (pluggable: logging / AWS SES) |
| **frontend** | 80 | React SPA (shop + admin panel) |

## Key Features

- **Outbox Pattern**: Reliable event delivery between services (orders → production, notifications)
- **Transactional Email**: Order confirmation, shipping, delivery and cancellation email via a pluggable provider (AWS SES in production, log-only locally)
- **Schema Isolation**: Each service owns its PostgreSQL schema
- **JWT Auth**: Stateless authentication with role-based access
- **Admin Panel**: Full management UI for all services
- **Shop UI**: Customer-facing catalog, cart, checkout, order tracking
- **User Accounts**: Registration, login, order history
- **Infrastructure Dashboard**: Real-time K8s cluster monitoring
- **Structured Logging**: JSON logs with correlation IDs for request tracing
- **Centralized Log Aggregation**: Loki + Fluent Bit for log collection and querying

## Quick Start

### Local Development

```bash
# Start PostgreSQL
docker compose up -d postgres

# Run a service
docker compose up --build catalog

# Health check
curl localhost:8002/healthz
```

### Deploy to AWS EKS

```bash
# Full deployment (creates EKS, RDS, deploys all services)
./deploy/full-deploy.sh

# Or step by step
make cluster-create    # Create EKS cluster (~15 min)
make rds-create        # Create RDS instance (~10 min)
make build-all         # Build all Docker images
make push-all          # Push to ECR
make deploy-services   # Deploy via Helm
```

### Helm Deployment

```bash
# Deploy individual services
helm upgrade --install users      deploy/charts/users      -n postershop
helm upgrade --install catalog    deploy/charts/catalog    -n postershop
helm upgrade --install inventory  deploy/charts/inventory  -n postershop
helm upgrade --install orders     deploy/charts/orders     -n postershop
helm upgrade --install production deploy/charts/production -n postershop
helm upgrade --install logistics  deploy/charts/logistics  -n postershop
helm upgrade --install payments   deploy/charts/payments   -n postershop
helm upgrade --install infra      deploy/charts/infra      -n postershop
helm upgrade --install notifications deploy/charts/notifications -n postershop
helm upgrade --install frontend   deploy/charts/frontend   -n postershop
```

## Database Configuration

The seven database-backed services use PostgreSQL with **schema-per-service** isolation via `search_path`; `payments` (checkout sessions live at Stripe) and `infra` (reads live Kubernetes state) are stateless and own no schema:

```
postgresql+psycopg2://<USER>:<PASS>@<RDS_HOST>:5432/<DB>?options=-csearch_path%3D<schema>
```

| Service | Schema | User |
|---------|--------|------|
| users | `users_schema` | `users_svc` |
| catalog | `catalog_schema` | `catalog_svc` |
| inventory | `inventory_schema` | `inventory_svc` |
| orders | `orders_schema` | `orders_svc` |
| production | `production_schema` | `production_svc` |
| logistics | `logistics_schema` | `logistics_svc` |
| notifications | `notifications_schema` | `notifications_svc` |

## Project Structure

```
shop-platform/
├── services/               # Backend microservices
│   ├── users/
│   ├── catalog/
│   ├── inventory/
│   ├── orders/
│   ├── production/
│   ├── logistics/
│   ├── payments/
│   ├── notifications/
│   └── infra/
├── frontend/               # React SPA
├── deploy/                 # Deployment resources
│   ├── charts/             # Helm charts
│   ├── infrastructure/     # EKS/RDS configs
│   ├── rds/                # Database init scripts
│   ├── secrets/            # AWS Secrets Manager
│   └── monitoring/         # Prometheus/Grafana
├── .github/workflows/      # CI/CD pipelines
└── docs/                   # Additional documentation
```

## Documentation

### Architecture & Design
- [Architecture Diagrams](docs/ARCHITECTURE.md) - Mermaid diagrams for system overview
- [Event Catalog](docs/EVENT_CATALOG.md) - All events, payloads, producers/consumers
- [API Contracts](docs/API_CONTRACTS.md) - Inter-service API specifications
- [Database Schema](docs/DATABASE_SCHEMA.md) - Tables, columns, relationships
- [Known Limitations](docs/KNOWN_LIMITATIONS.md) - Deliberately deferred features

### Development
- [Quick Reference](docs/QUICK_REFERENCE.md) - Ports, env vars, common commands
- [Development Guide](docs/DEVELOPMENT.md) - Local setup, commands, debugging
- [Environment Variables](docs/ENV_VARS.md) - All configuration options
- [Database Migrations](docs/MIGRATIONS.md) - Alembic migration workflow
- [Backlog](docs/BACKLOG.md) - Planned improvements and known issues

### Deployment
- [Deployment Guide](deploy/README.md) - EKS deployment instructions (includes AWS setup, OIDC, ECR)
- [Database Initialization](deploy/rds/README.md) - Schema setup
- [Secrets Management](deploy/secrets/README.md) - AWS Secrets Manager
- [Monitoring](deploy/monitoring/README.md) - Prometheus/Grafana
- [Centralized Logging](deploy/monitoring/LOGGING.md) - Loki + Fluent Bit

### Service Documentation
Each service has its own README with API endpoints, schemas, and usage:
- [Users](services/users/README.md) | [Catalog](services/catalog/README.md) | [Inventory](services/inventory/README.md)
- [Orders](services/orders/README.md) | [Production](services/production/README.md) | [Logistics](services/logistics/README.md)
- [Payments](services/payments/README.md) | [Infra](services/infra/README.md) | [Notifications](services/notifications/README.md)
- [Shared](services/shared/README.md)

## Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, Vite, TailwindCSS, React Query |
| Backend | Python, FastAPI, SQLAlchemy, Pydantic |
| Database | PostgreSQL (RDS) |
| Container | Docker |
| Orchestration | Kubernetes (EKS) |
| IaC | eksctl, Helm |
| CI/CD | GitHub Actions |
| Cloud | AWS (EKS, RDS, ECR, ALB) |

## API Endpoints

All services expose:
- `GET /healthz` - Health check
- `GET /metrics` - Prometheus metrics

Access via ALB:
```
http://<ALB_HOST>/api/users/...
http://<ALB_HOST>/api/catalog/...
http://<ALB_HOST>/api/orders/...
...
http://<ALB_HOST>/shop          # Customer shop
http://<ALB_HOST>/              # Admin panel
```

## License

MIT
