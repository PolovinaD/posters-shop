# AWS Configuration Guide

This guide explains how to configure AWS settings for the PosterShop platform.

## Required Configuration

### 1. Environment Variables

The following AWS-related variables need to be configured:

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region for deployment | `eu-north-1` |
| `AWS_ACCOUNT_ID` | Your AWS account ID | Auto-detected via `aws sts get-caller-identity` |

### 2. For Local Development / Makefile

The Makefile auto-detects your AWS account ID using the AWS CLI:

```bash
# These are auto-detected if AWS CLI is configured:
make ecr-login    # Login to ECR
make build-all    # Build all images
make push-all     # Push to ECR

# Or set explicitly:
AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 make push-all
```

### 3. For GitHub Actions CI/CD

Set these as repository variables (Settings → Secrets and variables → Actions → Variables):

| Variable | Example |
|----------|---------|
| `AWS_ACCOUNT_ID` | `123456789012` |
| `AWS_REGION` | `eu-north-1` |
| `EKS_CLUSTER` | `postershop` |

### 4. For Manual Deployment

When running `deploy/deploy.sh` or `deploy/full-deploy.sh`:

```bash
# Auto-detect from AWS CLI:
./deploy/deploy.sh

# Or set explicitly:
AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 ./deploy/deploy.sh
```

## Setting Up GitHub Actions OIDC

1. **Create OIDC Identity Provider** in AWS IAM:
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`

2. **Create IAM Role** for GitHub Actions:
   - Edit `trust-policy.json` with your values:
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

## Creating ECR Repositories

Create repositories for each service:

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=eu-north-1

for service in users catalog orders production logistics inventory payments infra frontend; do
  aws ecr create-repository \
    --repository-name $service \
    --region $AWS_REGION \
    --image-scanning-configuration scanOnPush=true
done
```

## Helm Chart Configuration

Helm charts use placeholder values by default. The deployment scripts automatically set the correct ECR registry:

```bash
# Automatic (recommended):
./deploy/deploy.sh

# Or manual override:
helm upgrade --install users ./deploy/charts/users \
  --set image.repository=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/users \
  --set image.tag=latest
```

## Quick Start

1. **Configure AWS CLI**:
   ```bash
   aws configure
   ```

2. **Create ECR repositories** (see above)

3. **Build and push images**:
   ```bash
   make build-all
   make push-all
   ```

4. **Create EKS cluster**:
   ```bash
   make cluster-create
   ```

5. **Deploy**:
   ```bash
   make deploy
   ```

## Troubleshooting

### "YOUR_AWS_ACCOUNT_ID" error
AWS CLI is not configured. Run `aws configure` or set `AWS_ACCOUNT_ID` explicitly.

### ECR login fails
Ensure you have the correct IAM permissions and run:
```bash
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

### Helm deployment fails with "image pull error"
1. Verify ECR repository exists
2. Verify image was pushed
3. Check EKS nodes have ECR pull permissions

