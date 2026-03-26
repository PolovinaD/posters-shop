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
              ┌─────┴─────┐     ┌─────────┐                             │
              │ payments  │     │  infra  │                             │
              │ (mock)    │     │ (k8s)   │                             │
              └───────────┘     └─────────┘                             │
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
| **payments** | 8000 | Mock Stripe-like checkout sessions |
| **infra** | 8000 | Kubernetes cluster introspection API |
| **frontend** | 80 | React SPA (shop + admin panel) |

## Key Features

- **Outbox Pattern**: Reliable event delivery between services (orders → production)
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
helm upgrade --install frontend   deploy/charts/frontend   -n postershop
```

## Database Configuration

All services use PostgreSQL with **schema-per-service** isolation via `search_path`:

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
| payments | `payments_schema` | `payments_svc` |

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
- [Thesis Snapshot](THESIS_SNAPSHOT.md) - Research context and decisions

### Development
- [Development Guide](docs/DEVELOPMENT.md) - Local setup, commands, debugging
- [Environment Variables](docs/ENV_VARS.md) - All configuration options
- [Database Migrations](docs/MIGRATIONS.md) - Alembic migration workflow
- [Backlog](docs/BACKLOG.md) - Planned improvements and known issues

### Deployment
- [Deployment Guide](deploy/README.md) - EKS deployment instructions
- [AWS Setup](docs/AWS_SETUP.md) - AWS resource configuration
- [Database Initialization](deploy/rds/README.md) - Schema setup
- [Secrets Management](deploy/secrets/README.md) - AWS Secrets Manager
- [Monitoring](deploy/monitoring/README.md) - Prometheus/Grafana
- [Centralized Logging](deploy/monitoring/LOGGING.md) - Loki + Fluent Bit

### Service Documentation
Each service has its own README with API endpoints, schemas, and usage:
- [Users](services/users/README.md) | [Catalog](services/catalog/README.md) | [Inventory](services/inventory/README.md)
- [Orders](services/orders/README.md) | [Production](services/production/README.md) | [Logistics](services/logistics/README.md)
- [Payments](services/payments/README.md) | [Infra](services/infra/README.md) | [Shared](services/shared/README.md)

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
