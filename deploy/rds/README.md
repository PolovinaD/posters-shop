# RDS Database Initialization

Scripts for initializing the PostgreSQL database on AWS RDS.

## Prerequisites

1. **RDS Instance**: PostgreSQL 14+ instance running
2. **Master Credentials**: Admin user with full privileges
3. **Network Access**: Ability to connect to RDS from your machine or a bastion host
4. **psql client**: PostgreSQL client installed

## Files

| File | Description |
|------|-------------|
| `01-create-schemas.sql` | Creates database schemas for each service |
| `02-create-users.sql` | Creates service-specific users (run with password vars) |
| `03-grant-permissions.sql` | Grants schema-level permissions to users |
| `init-all.sh` | Wrapper script to run all SQL files |
| `cleanup.sql` | Drops all users and schemas (for reset) |

## Quick Start

### Option 1: Using the wrapper script

```bash
# Set environment variables
export RDS_HOST="your-rds-endpoint.region.rds.amazonaws.com"
export RDS_PORT="5432"
export RDS_DATABASE="postershop"
export RDS_MASTER_USER="postgres"
export RDS_MASTER_PASSWORD="your-master-password"

# Generate secure passwords for service users
export USERS_SVC_PASSWORD=$(openssl rand -base64 24)
export CATALOG_SVC_PASSWORD=$(openssl rand -base64 24)
export ORDERS_SVC_PASSWORD=$(openssl rand -base64 24)
export PRODUCTION_SVC_PASSWORD=$(openssl rand -base64 24)
export LOGISTICS_SVC_PASSWORD=$(openssl rand -base64 24)
export INVENTORY_SVC_PASSWORD=$(openssl rand -base64 24)

# Run initialization
./init-all.sh

# Save passwords securely (e.g., AWS Secrets Manager)
echo "Save these passwords to AWS Secrets Manager:"
echo "USERS_SVC_PASSWORD=$USERS_SVC_PASSWORD"
echo "CATALOG_SVC_PASSWORD=$CATALOG_SVC_PASSWORD"
echo "ORDERS_SVC_PASSWORD=$ORDERS_SVC_PASSWORD"
echo "PRODUCTION_SVC_PASSWORD=$PRODUCTION_SVC_PASSWORD"
echo "LOGISTICS_SVC_PASSWORD=$LOGISTICS_SVC_PASSWORD"
echo "INVENTORY_SVC_PASSWORD=$INVENTORY_SVC_PASSWORD"
```

### Option 2: Using Kubernetes Job

For production, you can run initialization via a Kubernetes Job:

```bash
kubectl apply -f init-job.yaml -n postershop
```

### Option 3: Manual execution

```bash
# Connect to RDS
psql -h $RDS_HOST -p 5432 -U postgres -d postershop

# Run each script in order
\i 01-create-schemas.sql
\i 02-create-users.sql  -- Edit passwords first!
\i 03-grant-permissions.sql
```

## Security Notes

1. **Never commit real passwords** to version control
2. **Use AWS Secrets Manager** to store service passwords
3. **Rotate passwords** periodically
4. **Enable SSL** for RDS connections (`sslmode=require`)
5. **Use IAM authentication** when possible for enhanced security

## Kubernetes Secret Generation

After initialization, create Kubernetes secrets with the connection strings:

```bash
# Generate base64 encoded connection strings
echo -n "postgresql://users_svc:$USERS_SVC_PASSWORD@$RDS_HOST:5432/postershop?sslmode=require&options=-csearch_path%3Dusers" | base64
# ... repeat for other services

# Or use kubectl directly
kubectl create secret generic postershop-db \
  --from-literal=DATABASE_URL_USERS="postgresql://users_svc:$USERS_SVC_PASSWORD@$RDS_HOST:5432/postershop?sslmode=require&options=-csearch_path%3Dusers" \
  --from-literal=DATABASE_URL_CATALOG="postgresql://catalog_svc:$CATALOG_SVC_PASSWORD@$RDS_HOST:5432/postershop?sslmode=require&options=-csearch_path%3Dcatalog" \
  --from-literal=DATABASE_URL_ORDERS="postgresql://orders_svc:$ORDERS_SVC_PASSWORD@$RDS_HOST:5432/postershop?sslmode=require&options=-csearch_path%3Dorders" \
  --from-literal=DATABASE_URL_PRODUCTION="postgresql://production_svc:$PRODUCTION_SVC_PASSWORD@$RDS_HOST:5432/postershop?sslmode=require&options=-csearch_path%3Dproduction" \
  --from-literal=DATABASE_URL_LOGISTICS="postgresql://logistics_svc:$LOGISTICS_SVC_PASSWORD@$RDS_HOST:5432/postershop?sslmode=require&options=-csearch_path%3Dlogistics" \
  --from-literal=DATABASE_URL_INVENTORY="postgresql://inventory_svc:$INVENTORY_SVC_PASSWORD@$RDS_HOST:5432/postershop?sslmode=require&options=-csearch_path%3Dinventory" \
  -n postershop
```

## Troubleshooting

### Cannot connect to RDS
- Check security group allows inbound on port 5432
- Verify RDS is publicly accessible (or use VPN/bastion)
- Ensure master username/password is correct

### Permission denied errors
- Ensure you're connected as the master user
- Check that schemas exist before granting permissions

### User already exists
- Safe to ignore if passwords haven't changed
- Use `cleanup.sql` to reset everything

