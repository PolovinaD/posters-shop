# Database Migrations

PosterShop uses **Alembic** for database schema versioning and migrations.

## Architecture

Each service manages its own migrations independently:

```
services/
├── orders/
│   ├── alembic/
│   │   ├── versions/
│   │   │   ├── 001_initial_schema.py
│   │   │   ├── 002_shipping_address.py
│   │   │   └── 003_escrow.py
│   │   ├── env.py
│   │   └── script.py.mako
│   └── alembic.ini
├── inventory/
│   └── alembic/
│       └── ...
└── ...
```

## Schema Isolation

Each service has its own PostgreSQL schema:

| Service | Schema |
|---------|--------|
| orders | `orders_schema` |
| inventory | `inventory_schema` |
| production | `production_schema` |
| users | `users_schema` |
| catalog | `catalog_schema` |
| logistics | `logistics_schema` |
| notifications | `notifications_schema` |
| designs | `designs_schema` |

Alembic only manages tables within its service's schema via the `include_object` filter.

## Local Development

### Running Migrations

```bash
# Navigate to service
cd services/orders

# Set database URL
export DATABASE_URL="postgresql://user:pass@localhost:5432/postershop?options=-csearch_path%3Dorders_schema"

# Apply all migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current version
alembic current

# Show migration history
alembic history
```

Under docker-compose you do not run these by hand: every DB-backed service has a
`<service>-migrate` sidecar (`users-migrate` … `notifications-migrate`, `designs-migrate`)
that runs `alembic upgrade head` against the service's own user and `search_path`, and the
service `depends_on` it with `condition: service_completed_successfully`. The sidecar is a
**separate image** from the service (same `build:` context, no shared `image:` key), so
after adding a migration rebuild both — `docker compose build <service>-migrate`, then
`docker compose build <service>` — or the stale sidecar runs the old tree, applies nothing
and exits 0.

### Creating New Migrations

```bash
cd services/orders

# Auto-generate from model changes
alembic revision --autogenerate -m "add payment_method column"

# Create empty migration (for data migrations)
alembic revision -m "backfill payment_method"
```

### Migration Best Practices

1. **Review auto-generated migrations** - Alembic may miss some changes or generate incorrect code
2. **Test both upgrade and downgrade** - Ensure rollbacks work
3. **Keep migrations small** - One logical change per migration
4. **Add data migrations carefully** - Consider running them separately from schema changes

## Kubernetes Deployment

Migrations run automatically as a Helm pre-install/pre-upgrade hook.

### How It Works

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  helm upgrade   │────▶│  Migration Job  │────▶│  Deployment     │
│                 │     │  (hook)         │     │  (main service) │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              │ alembic upgrade head
                              ▼
                        ┌─────────────────┐
                        │    Database     │
                        └─────────────────┘
```

### Migration Job

Each **database-backed** service has a Helm hook that runs migrations (eight charts:
users, catalog, inventory, orders, production, logistics, notifications, designs). The
stateless services (`payments`, `infra`) own no schema, have no Alembic setup, and their
charts contain no `migration-job.yaml` at all:

```yaml
# deploy/charts/orders/templates/migration-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: migrate
          command: ["alembic", "upgrade", "head"]
```

### Configuration

Enable/disable migrations in `values.yaml`:

```yaml
migrations:
  enabled: true
  secretName: postershop-db
  secretKey: DATABASE_URL_ORDERS
```

### Checking Migration Status

```bash
# Check if migration job completed
kubectl get jobs -n postershop -l component=migration

# View migration logs
kubectl logs -n postershop -l app=orders,component=migration

# Manual migration (if needed)
kubectl exec -it deploy/orders -n postershop -- alembic current
```

## CI/CD Integration

### GitHub Actions

The deployment workflow automatically runs migrations:

1. Build image with Alembic installed
2. Deploy with Helm (triggers migration hook)
3. Migration job runs before main deployment
4. If migration fails, deployment is blocked

### Rollback Procedure

If a deployment fails after migration:

```bash
# 1. Identify the failed migration
kubectl logs -n postershop job/orders-migrate-<revision>

# 2. Manually rollback if needed
kubectl run -it --rm alembic-fix --image=<orders-image> \
  --env="DATABASE_URL=$DB_URL" \
  -- alembic downgrade -1

# 3. Fix the migration and redeploy
```

## Version Tracking

Alembic stores versions in a `alembic_version` table within each schema:

```sql
-- Check current version
SELECT * FROM orders_schema.alembic_version;

-- Result: version_num = '003'
```

### Current revisions

Every revision file in the repository, in upgrade order (16 files across 8 services).
Revision ids are what `alembic_version` stores; users names its revisions after the file.

| Service | Files (revision id) |
|---------|---------------------|
| orders | `001_initial_schema.py` (`001`) → `002_shipping_address.py` (`002`) → `003_escrow.py` (`003`) — escrow columns + `ix_orders_escrow_status` |
| users | `001_initial_schema.py` (`001`) → `002_add_refresh_tokens.py` (`002_add_refresh_tokens`) → `003_wallet_address.py` (`003_wallet_address`) — `users.wallet_address` |
| logistics | `001_initial_schema.py` (`001`) → `002_delivery_address.py` (`002`) → `003_courier_binding.py` (`003`) — `courier_id`, `courier_wallet`, `courier_bound_at` |
| catalog | `001_initial_schema.py` (`001`) → `002_product_variants.py` (`002`) → `003_product_listed.py` (`003`) — `products.listed` (boolean, NOT NULL, default true; custom AI motifs are `false`) |
| inventory | `001_initial_schema.py` (`001`) |
| production | `001_initial_schema.py` (`001`) |
| notifications | `001_initial_schema.py` (`001`) |
| designs | `001_initial_schema.py` (`001`) — `generations`, `saved_prompts`, `style_profiles`, `purchases`, `processed_events` |

## Troubleshooting

### "Target database is not up to date"

The database has unapplied migrations:

```bash
alembic upgrade head
```

### "Can't locate revision"

Migration file is missing or corrupted:

```bash
# Check what Alembic expects
alembic history

# Check what's in database
alembic current

# If needed, stamp to a known version
alembic stamp 001
```

### "Relation already exists"

Table was created outside of Alembic:

```bash
# Mark migration as applied without running it
alembic stamp head
```

### Migration Conflicts

If two developers create migrations with same parent:

```bash
# Show conflicting heads
alembic heads

# Merge heads
alembic merge -m "merge heads" head1 head2
```

## Adding New Services

**First decide whether the service needs a database at all.** Two of the ten backend
services are stateless and deliberately have no migrations:

| Service | State |
|---------|-------|
| payments | None — checkout sessions live at Stripe, escrow state on chain and on the orders row |
| infra | None — reads live Kubernetes state |
| ~~notifications~~ | No longer applies — now DB-backed (`notifications_schema`, `processed_events`); has a migration job (quick-260815-m0m) |

The newest DB-backed service, `designs` (Phase 9), is the reference for the full checklist:
`services/designs/alembic/` (env.py with `version_table_schema=designs_schema`, one
revision), `designs_schema` / `designs_svc` in `db/init.sql` and in `full-deploy.sh`'s RDS
SQL, the `designs-migrate` compose sidecar, `DATABASE_URL_DESIGNS` in the `postershop-db`
ExternalSecret, and `templates/migration-job.yaml` in `deploy/charts/designs`.

For these, skip this entire section and **delete `templates/migration-job.yaml` from the
chart** if it was copied from a database-backed service. A migration hook on a service
with no `alembic/` directory fails the Helm install.

To add migrations to a new database-backed service:

```bash
cd services/new-service

# Initialize Alembic
pip install alembic
alembic init alembic

# Configure env.py (copy from existing service and modify)
# Set SCHEMA_NAME and model imports

# Create initial migration
alembic revision --autogenerate -m "initial schema"

# Add migration job to Helm chart
# Copy from existing service's templates/migration-job.yaml
```

## Migration Checklist

Before deploying:

- [ ] Migration tested locally with `alembic upgrade head`
- [ ] Rollback tested with `alembic downgrade -1`
- [ ] Migration reviewed for correctness
- [ ] No breaking changes to columns in use
- [ ] Data migration handles existing records

After deploying:

- [ ] Migration job completed successfully
- [ ] Service pods started without errors
- [ ] Database schema matches expected state
