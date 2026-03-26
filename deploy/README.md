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

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `eu-north-1` | AWS region |
| `CLUSTER_NAME` | `postershop` | EKS cluster name |
| `NAMESPACE` | `postershop` | Kubernetes namespace |
| `DB_PASSWORD` | (prompt) | RDS master password |

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

The platform uses **AWS Secrets Manager** as the single source of truth for all secrets,
with **External Secrets Operator** automatically syncing them to Kubernetes.

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

