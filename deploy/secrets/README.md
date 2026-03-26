# Secrets Management with AWS Secrets Manager

This directory contains resources for managing secrets using AWS Secrets Manager
and the External Secrets Operator (ESO).

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  AWS Secrets        │────▶│  External Secrets   │────▶│  Kubernetes         │
│  Manager            │     │  Operator           │     │  Secrets            │
│                     │     │                     │     │                     │
│  postershop/        │     │  SecretStore        │     │  postershop-db      │
│  ├── database       │     │  ExternalSecret     │     │  postershop-jwt     │
│  ├── jwt            │     │                     │     │  postershop-stripe  │
│  └── stripe         │     │                     │     │                     │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

## Secrets in AWS Secrets Manager

| Secret Name            | Description                    | Keys                                                    |
|------------------------|--------------------------------|---------------------------------------------------------|
| `postershop/passwords` | All service & RDS passwords    | `USERS_SVC_PASSWORD`, `DB_PASSWORD`, `JWT_SECRET`, etc. |
| `postershop/database`  | Database connection strings    | `DATABASE_URL_USERS`, `DATABASE_URL_CATALOG`, etc.      |
| `postershop/jwt`       | JWT signing secret             | `JWT_SECRET`                                            |
| `postershop/stripe`    | Stripe webhook secret          | `WEBHOOK_SECRET`                                        |

## How It Works

1. **Deploy script** generates all passwords (including RDS master password) and stores them in AWS Secrets Manager
2. **External Secrets Operator** watches for `ExternalSecret` resources
3. ESO reads secrets from AWS Secrets Manager and creates K8s Secrets
4. **Services** consume secrets as normal K8s Secrets (no code changes needed)

**No local files are used** - AWS Secrets Manager is the single source of truth.

## Benefits

- **Single source of truth**: All passwords stored exclusively in AWS SM (no local files)
- **No mismatches**: Same password used for RDS creation and application configuration
- **Rotation ready**: Change in AWS SM → ESO updates K8s Secret → Pods restart
- **Audit trail**: AWS CloudTrail logs all secret access
- **Cost**: ~$0.40/secret/month + $0.05 per 10,000 API calls

## Files

| File                    | Description                                      |
|-------------------------|--------------------------------------------------|
| `iam-policy.json`       | IAM policy for ESO to access Secrets Manager     |
| `secret-store.yaml`     | SecretStore CRD - connection to AWS SM           |
| `external-secrets.yaml` | ExternalSecret CRDs - what to sync               |

## Manual Operations

### View secrets in AWS Secrets Manager

```bash
# List all postershop secrets
aws secretsmanager list-secrets --filter Key=name,Values=postershop/

# Get a specific secret value
aws secretsmanager get-secret-value --secret-id postershop/jwt
```

### Rotate a secret

```bash
# Update the secret in AWS
aws secretsmanager put-secret-value \
    --secret-id postershop/jwt \
    --secret-string '{"JWT_SECRET":"new-secret-value"}'

# ESO will sync within refreshInterval (1h by default)
# Or force immediate sync:
kubectl annotate externalsecret postershop-jwt -n postershop \
    force-sync=$(date +%s) --overwrite
```

### Check sync status

```bash
# View ExternalSecret status
kubectl get externalsecrets -n postershop

# Check for sync errors
kubectl describe externalsecret postershop-db -n postershop
```
