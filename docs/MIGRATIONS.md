# Database Migrations

PosterShop uses **Alembic** for database schema versioning and migrations.

## Architecture

Each service manages its own migrations independently:

```
services/
├── orders/
│   ├── alembic/
│   │   ├── versions/
│   │   │   └── 001_initial_schema.py
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

Each **database-backed** service has a Helm hook that runs migrations. The stateless
services (`payments`, `infra`, `notifications`) own no schema, have no Alembic setup, and
their charts contain no `migration-job.yaml` at all:

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

-- Result: version_num = '001'
```

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

**First decide whether the service needs a database at all.** Three of the nine backend
services are stateless and deliberately have no migrations:

| Service | State |
|---------|-------|
| payments | In-memory checkout sessions |
| infra | None — reads live Kubernetes state |
| notifications | In-memory idempotency set only |

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
