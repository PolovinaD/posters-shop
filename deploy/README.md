# PosterShop Platform - Deployment Guide

Complete deployment solution for the PosterShop microservices platform on AWS EKS.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         VPC (10.0.0.0/16)                              │ │
│  │                                                                        │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │ │
│  │  │                    Public Subnets                                │  │ │
│  │  │  ┌─────────────────────────────────────────────────────────┐    │  │ │
│  │  │  │              AWS Application Load Balancer              │    │  │ │
│  │  │  └─────────────────────────┬───────────────────────────────┘    │  │ │
│  │  └────────────────────────────┼────────────────────────────────────┘  │ │
│  │                               │                                        │ │
│  │  ┌────────────────────────────┼────────────────────────────────────┐  │ │
│  │  │              Private Subnets (EKS Nodes)                        │  │ │
│  │  │                            │                                    │  │ │
│  │  │  ┌─────────────────────────┴───────────────────────────────┐   │  │ │
│  │  │  │                   EKS Cluster                            │   │  │ │
│  │  │  │                                                          │   │  │ │
│  │  │  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐            │   │  │ │
│  │  │  │  │ Users  │ │Catalog │ │ Orders │ │  ...   │            │   │  │ │
│  │  │  │  └────────┘ └────────┘ └────────┘ └────────┘            │   │  │ │
│  │  │  │                                                          │   │  │ │
│  │  │  │  ┌──────────────────────────────────────────────────┐   │   │  │ │
│  │  │  │  │              Prometheus + Grafana                 │   │   │  │ │
│  │  │  │  └──────────────────────────────────────────────────┘   │   │  │ │
│  │  │  └──────────────────────────────────────────────────────────┘   │  │ │
│  │  │                            │                                    │  │ │
│  │  └────────────────────────────┼────────────────────────────────────┘  │ │
│  │                               │                                        │ │
│  │  ┌────────────────────────────┼────────────────────────────────────┐  │ │
│  │  │              Private Subnets (Database)                         │  │ │
│  │  │                            │                                    │  │ │
│  │  │  ┌─────────────────────────┴───────────────────────────────┐   │  │ │
│  │  │  │                  RDS PostgreSQL                          │   │  │ │
│  │  │  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐            │   │  │ │
│  │  │  │  │ users  │ │catalog │ │ orders │ │  ...   │  schemas   │   │  │ │
│  │  │  │  └────────┘ └────────┘ └────────┘ └────────┘            │   │  │ │
│  │  │  └──────────────────────────────────────────────────────────┘   │  │ │
│  │  └─────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### One-Command Deployment

```bash
# Full deployment (creates everything from scratch)
make deploy

# Or with the script directly
./deploy/full-deploy.sh
```

### Step-by-Step Deployment

```bash
# 1. Create EKS cluster (~15 min)
make cluster-create

# 2. Create RDS instance (~10 min)
make rds-create

# 3. Initialize database
make rds-init

# 4. Build and push images
make build-all push-all

# 5. Deploy services
make deploy-services

# 6. Install monitoring
make monitoring-install
```

## Directory Structure

```
deploy/
├── README.md                    # This file
├── full-deploy.sh               # Master deployment script
├── deploy.sh                    # Service deployment script
├── secrets-template.yaml        # K8s secrets template
│
├── infrastructure/              # AWS infrastructure
│   ├── eksctl-cluster.yaml      # EKS cluster definition
│   └── rds.yaml                 # RDS CloudFormation template
│
├── charts/                      # Helm charts
│   ├── users/
│   ├── catalog/
│   ├── orders/
│   ├── production/
│   ├── logistics/
│   ├── inventory/
│   ├── payments/
│   ├── notifications/
│   ├── infra/
│   └── frontend/
│
├── rds/                         # Database initialization
│   ├── README.md
│   ├── init-all.sh              # Run all SQL scripts
│   ├── 01-create-schemas.sql
│   ├── 02-create-users.sql
│   ├── 03-grant-permissions.sql
│   ├── cleanup.sql
│   └── init-job.yaml            # K8s Job for in-cluster init
│
├── secrets/                     # Secrets management (AWS Secrets Manager)
│   ├── README.md
│   ├── iam-policy.json          # IAM policy for External Secrets
│   ├── secret-store.yaml        # SecretStore CRD
│   └── external-secrets.yaml    # ExternalSecret CRDs
│
└── monitoring/                  # Prometheus + Grafana + Loki
    ├── README.md
    ├── LOGGING.md               # Centralized logging guide
    ├── prometheus-values.yaml
    ├── loki-values.yaml         # Loki configuration
    ├── fluent-bit-values.yaml   # Fluent Bit configuration
    ├── servicemonitors.yaml
    ├── alertrules.yaml
    ├── grafana-dashboard-*.json
    └── grafana-dashboards-configmap.yaml
```

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI | 2.x | AWS operations |
| eksctl | 0.150+ | EKS cluster management |
| kubectl | 1.28+ | Kubernetes CLI |
| helm | 3.x | Package management |
| docker | 20+ | Container builds |
| psql | 14+ | Database initialization |
| jq | 1.6+ | JSON processing |

## AWS Setup Details

### Account ID Auto-detection

The Makefile and deploy scripts auto-detect your AWS account ID via the AWS CLI:

```bash
# These are auto-detected if AWS CLI is configured:
make ecr-login    # Login to ECR
make build-all    # Build all images
make push-all     # Push to ECR
```

Override explicitly when needed (e.g., switching regions or running outside `aws configure`):

```bash
AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 make push-all
```

When running `deploy/deploy.sh` or `deploy/full-deploy.sh` directly the same overrides apply:

```bash
# Auto-detect from AWS CLI:
./deploy/deploy.sh

# Or set explicitly:
AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 ./deploy/deploy.sh
```

### GitHub Actions OIDC

Set these as repository variables (Settings → Secrets and variables → Actions → Variables):

| Variable | Example |
|----------|---------|
| `AWS_ACCOUNT_ID` | `123456789012` |
| `AWS_REGION` | `eu-north-1` |
| `EKS_CLUSTER` | `postershop` |

Then provision the OIDC identity provider and the IAM role:

1. **Create OIDC Identity Provider** in AWS IAM:
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`

2. **Create IAM Role** for GitHub Actions. Edit `trust-policy.json` with your values:
   - Replace `YOUR_AWS_ACCOUNT_ID` with your account ID
   - Replace `YOUR_GITHUB_ORG/YOUR_REPO` with your GitHub repository

   ```bash
   aws iam create-role \
     --role-name github-actions-role \
     --assume-role-policy-document file://trust-policy.json
   ```

3. **Attach Required Policies**:

   ```bash
   # ECR access
   aws iam attach-role-policy \
     --role-name github-actions-role \
     --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser

   # EKS access
   aws iam attach-role-policy \
     --role-name github-actions-role \
     --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy
   ```

### ECR Repository Creation

Create one repository per service:

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=eu-north-1

for service in users catalog orders production logistics inventory payments notifications frontend infra; do
  aws ecr create-repository \
    --repository-name $service \
    --region $AWS_REGION \
    --image-scanning-configuration scanOnPush=true
done
```

### Helm Chart Image Overrides

Helm charts use placeholder values by default. The deployment scripts automatically point them at the right ECR registry, but you can override manually:

```bash
# Automatic (recommended):
./deploy/deploy.sh

# Or manual override:
helm upgrade --install users ./deploy/charts/users \
  --set image.repository=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/users \
  --set image.tag=latest
```

### AWS-Specific Troubleshooting

**"YOUR_AWS_ACCOUNT_ID" error** — AWS CLI is not configured. Run `aws configure` or set `AWS_ACCOUNT_ID` explicitly.

**ECR login fails** — Ensure you have the correct IAM permissions and run:

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin \
    $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

**Helm deployment fails with "image pull error"** —

1. Verify the ECR repository exists
2. Verify the image was pushed
3. Check that EKS nodes have ECR pull permissions

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `eu-north-1` | AWS region |
| `AWS_ACCOUNT_ID` | (auto-detected via `aws sts get-caller-identity`) | AWS account ID used for ECR registry URLs |
| `CLUSTER_NAME` | `postershop` | EKS cluster name |
| `NAMESPACE` | `postershop` | Kubernetes namespace |
| `DB_PASSWORD` | (prompt) | RDS master password |
| `EMAIL_PROVIDER` | `logging` (code default) | Notifications email transport: `ses` for real delivery, anything else uses the credential-free logging provider |
| `EMAIL_FROM` | `no-reply@postershop.example` | Sender address. Must be a **verified SES identity** in `SES_REGION` when `EMAIL_PROVIDER=ses` |
| `SES_REGION` | `eu-central-1` | Region whose SES holds the verified sender identity. Deliberately independent of `AWS_REGION` (see below) |

## Email Delivery Setup (SES via IRSA)

The `notifications` service sends transactional email on order-lifecycle events.
Its transport is pluggable:

| `EMAIL_PROVIDER` | Provider | AWS needed? | Intended environment |
|------------------|----------|-------------|----------------------|
| unset / anything but `ses` | `LoggingProvider` — renders the email into the structured log | No | Local dev, docker-compose, thesis demo |
| `ses` | `SesProvider` — real send through AWS SES | Yes (IRSA role) | Production |

The chart ships `EMAIL_PROVIDER=logging` so that a plain `helm install` works with
no AWS setup at all. **Production must explicitly opt in to SES** by completing the
three steps below and then setting `EMAIL_PROVIDER=ses`.

### 1. Verify a sender identity in SES

```bash
aws ses verify-email-identity \
  --email-address no-reply@postershop.example \
  --region eu-central-1
```

Confirm the verification link that SES emails to that address. Until the identity is
verified, every send fails. A whole verified domain works too, and is preferable for
production because it removes the per-address confirmation step.

> **On the region difference — this is intentional, not a bug.**
> The EKS cluster runs in `eu-north-1` (`AWS_REGION`), while `SES_REGION` defaults to
> `eu-central-1`. SES is a regional service and a verified sender identity lives in
> whichever region it was verified in; that region does not have to match the region
> the calling workload runs in. `eu-north-1` also has narrower SES availability than
> `eu-central-1`. If you verify your identity in `eu-north-1` instead, simply set
> `SES_REGION=eu-north-1` — the two values are independent by design.

### 2. Create the IAM role for IRSA

IRSA (*IAM Roles for Service Accounts*) lets the pod assume an IAM role through its
Kubernetes ServiceAccount, so **no AWS access key is ever stored** — not in the image,
not in a Kubernetes Secret, not in Secrets Manager.

```bash
eksctl create iamserviceaccount \
  --name notifications \
  --namespace postershop \
  --cluster postershop \
  --region eu-north-1 \
  --attach-policy-arn arn:aws:iam::aws:policy/AmazonSESFullAccess \
  --approve
```

For least privilege, prefer a customer-managed policy over `AmazonSESFullAccess`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail"],
      "Resource": "*"
    }
  ]
}
```

### 3. Point the chart at the ServiceAccount

`eksctl` creates the ServiceAccount with the `eks.amazonaws.com/role-arn` annotation
already applied, so the chart only needs to consume it. The Deployment emits
`serviceAccountName` whenever `serviceAccount.name` is non-empty, and omits it entirely
otherwise — which is why a plain `helm install` still runs under the namespace default
ServiceAccount with no AWS identity.

`env` is a list, so `--set env[N].value=…` depends on positional indices that shift
whenever the list changes. Use an override file instead:

```yaml
# notifications-prod.yaml
serviceAccount:
  create: false
  name: notifications

env:
  - name: SERVICE_NAME
    value: "notifications"
  - name: LOG_LEVEL
    value: "INFO"
  - name: EMAIL_PROVIDER
    value: "ses"
  - name: EMAIL_FROM
    value: "no-reply@postershop.example"
  - name: SES_REGION
    value: "eu-central-1"
  - name: CORS_ORIGINS
    value: "https://shop.example.com"
```

```bash
helm upgrade --install notifications deploy/charts/notifications \
  --namespace postershop \
  -f notifications-prod.yaml
```

Helm replaces lists wholesale rather than merging them, so the override must restate
every `env` entry, not just the one being changed.

Confirm the binding actually rendered before installing:

```bash
helm template notifications deploy/charts/notifications \
  -f notifications-prod.yaml | grep serviceAccountName
# expected: "      serviceAccountName: notifications" (no leading '#')
```

If that prints nothing, `serviceAccount.name` did not reach the chart and the pod would
run under the default ServiceAccount — boto3 would then find no SES credentials and every
send would return `503`, which the orders outbox retries five times per event before
abandoning it.

### Alternative: let the chart own the ServiceAccount

If you created the IAM role without `eksctl` (so no ServiceAccount exists yet), the chart
can create and annotate it. Set `create: true` and supply the role ARN:

```yaml
serviceAccount:
  create: true
  name: notifications
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::<ACCOUNT_ID>:role/postershop-notifications-ses
```

The IAM role's trust policy must still name this ServiceAccount and the cluster's OIDC
provider; Helm creates the Kubernetes object, not the AWS role. Do not combine this with
the `eksctl` path above — `eksctl` already created the ServiceAccount, and `create: true`
would make Helm try to take ownership of an object it does not own.

If you manage the ServiceAccount outside Helm entirely, annotate it directly and leave
`create: false`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: notifications
  namespace: postershop
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::<ACCOUNT_ID>:role/postershop-notifications-ses
```

### Verifying

```bash
# The pod should have the IRSA env vars injected by the EKS webhook
kubectl exec -n postershop deploy/notifications -- env | grep AWS_ROLE_ARN

# Watch the send path
kubectl logs -n postershop deploy/notifications -f
```

With the logging provider, a successful send appears as an `Email (logging provider)`
log line carrying the rendered subject and body. With SES, a failure raises `503` so the
orders outbox retries; check `notifications_email_send_failures_total` in Prometheus.

## Useful Commands

### Local Development
```bash
make dev              # Start local environment
make dev-logs         # Tail all logs
make dev-test         # Health check all services
make dev-seed         # Seed sample data
make dev-db           # Connect to local PostgreSQL
```

### Kubernetes
```bash
make k-pods           # List all pods
make k-status         # Full status overview
make k-logs SVC=orders  # Tail service logs
make k-restart SVC=orders  # Restart deployment
```

### Monitoring
```bash
make monitoring-port-forward  # Grafana at localhost:3001
```

## Cost Estimation

Minimal production setup (~$200-250/month):

| Resource | Type | Monthly Cost |
|----------|------|--------------|
| EKS Control Plane | - | ~$73 |
| EC2 (2x t3.large) | On-Demand | ~$120 |
| RDS (db.t3.micro) | Single-AZ | ~$15 |
| NAT Gateway | Single | ~$32 |
| ALB | - | ~$20 |

For development/testing, you can reduce costs by:
- Using spot instances for nodes
- Using smaller RDS instance
- Destroying cluster when not in use

## Cleanup

```bash
# Delete services only
kubectl delete namespace postershop

# Delete everything (cluster + RDS)
make rds-delete
make cluster-delete
```

## Troubleshooting

### Pods not starting
```bash
kubectl describe pod <pod-name> -n postershop
kubectl logs <pod-name> -n postershop
```

### Database connection issues
```bash
# Test from within cluster
kubectl run -it --rm debug --image=postgres:16 --restart=Never -- \
  psql "postgresql://user:pass@rds-endpoint:5432/postershop?sslmode=require"
```

### ALB not getting DNS
```bash
kubectl describe ingress frontend -n postershop
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
```

## Secrets Management

The platform uses **AWS Secrets Manager** as the single source of truth for every *stored*
secret — database passwords, the JWT signing key, and the Stripe keys — with
**External Secrets Operator** automatically syncing them to Kubernetes.

> **Carve-out: IRSA-based AWS auth is deliberately outside this flow.**
> The `notifications` service reaches AWS SES through IRSA (*IAM Roles for Service
> Accounts*), which mints short-lived credentials from the pod's ServiceAccount at
> runtime. There is no access key to store, so nothing about SES authentication lives in
> Secrets Manager. The same applies to any other workload that assumes an IAM role rather
> than holding a key. Secrets Manager remains the single source of truth for stored
> secrets; credentials that are never stored simply do not enter it.
> See [Email Delivery Setup (SES via IRSA)](#email-delivery-setup-ses-via-irsa).

### How it works

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  AWS Secrets        │────▶│  External Secrets   │────▶│  Kubernetes         │
│  Manager            │     │  Operator           │     │  Secrets            │
│                     │     │                     │     │                     │
│  postershop/        │     │  SecretStore        │     │  postershop-db      │
│  ├── passwords      │     │  ExternalSecret     │     │  postershop-jwt     │
│  ├── database       │     │                     │     │  postershop-stripe  │
│  ├── jwt            │     │                     │     │                     │
│  └── stripe         │     │                     │     │                     │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

### Benefits

- **Single source of truth**: No password mismatches between DB init and K8s secrets
- **Automatic sync**: External Secrets Operator keeps K8s secrets in sync
- **Rotation ready**: Update in AWS SM → ESO syncs → pods restart
- **Audit trail**: AWS CloudTrail logs all secret access
- **Persistent across teardown**: Secrets survive `make cloud-down`

### Manual operations

```bash
# View secrets in AWS
aws secretsmanager list-secrets --filter Key=name,Values=postershop/

# Force secret sync
kubectl annotate externalsecret postershop-db -n postershop force-sync=$(date +%s) --overwrite

# Check sync status
kubectl get externalsecrets -n postershop
```

### Cleanup

By default, `make cloud-down` preserves secrets for reuse. To delete everything:

```bash
make cloud-clean-all  # Deletes secrets, ECR images, and infrastructure
```

## Security Checklist

- [x] Secrets stored in AWS Secrets Manager
- [x] External Secrets Operator for K8s sync
- [ ] RDS deletion protection enabled
- [ ] RDS Multi-AZ for production
- [ ] VPC endpoints for ECR (to avoid NAT costs)
- [ ] Network policies for pod isolation
- [ ] Pod security policies/standards
- [ ] TLS certificates for ALB
- [ ] WAF rules for ALB

