SHELL := /bin/bash

# ============================================================
# PosterShop Platform - Makefile
# ============================================================
# Quick commands for local development and cloud deployment.
#
# Usage:
#   make help         - Show all available commands
#   make dev          - Start local development environment
#   make deploy       - Full production deployment
# ============================================================

# Load .env file if it exists
ifneq (,$(wildcard ./.env))
    include .env
    export
endif

# Configuration (can be overridden by .env or command line)
AWS_PROFILE ?= private
AWS_REGION ?= eu-north-1
CLUSTER_NAME ?= postershop
NAMESPACE ?= postershop
MONITORING_NS ?= monitoring
# IMPORTANT: Expected account ID for safety checks
EXPECTED_ACCOUNT_ID ?= 553967852170
AWS_ACCOUNT_ID ?= $(shell AWS_PROFILE=$(AWS_PROFILE) aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "UNKNOWN")
ECR_REGISTRY ?= $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com

.PHONY: help
help: ## Show this help
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║              PosterShop Platform - Commands                  ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Local Development:"
	@awk 'BEGIN {FS = ":.*##"; printf ""} /^[a-zA-Z_-]+:.*?##/ { if ($$2 ~ /local/) printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""
	@echo "Cloud Deployment:"
	@awk 'BEGIN {FS = ":.*##"; printf ""} /^[a-zA-Z_-]+:.*?##/ { if ($$2 ~ /cloud|deploy/) printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""
	@echo "Utilities:"
	@awk 'BEGIN {FS = ":.*##"; printf ""} /^[a-zA-Z_-]+:.*?##/ { if ($$2 !~ /local|cloud|deploy/) printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ============================================================
# Safety Checks (IMPORTANT: Run before any cloud operations)
# ============================================================

.PHONY: verify
verify: ## Verify AWS credentials and kubectl context (RUN THIS FIRST!)
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║                  CREDENTIAL VERIFICATION                      ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Expected Account: $(EXPECTED_ACCOUNT_ID)"
	@echo "AWS Profile:      $(AWS_PROFILE)"
	@echo ""
	@echo "Checking AWS credentials..."
	@CURRENT_ACCOUNT=$$(AWS_PROFILE=$(AWS_PROFILE) aws sts get-caller-identity --query Account --output text 2>/dev/null); \
	if [ "$$CURRENT_ACCOUNT" = "$(EXPECTED_ACCOUNT_ID)" ]; then \
		echo "✅ AWS Account: $$CURRENT_ACCOUNT (CORRECT - Private)"; \
	else \
		echo "❌ AWS Account: $$CURRENT_ACCOUNT (WRONG! Expected $(EXPECTED_ACCOUNT_ID))"; \
		echo ""; \
		echo "⚠️  STOP! You are using the wrong AWS account!"; \
		echo "   Run: export AWS_PROFILE=private"; \
		exit 1; \
	fi
	@echo ""
	@echo "Checking kubectl context..."
	@CURRENT_CTX=$$(kubectl config current-context 2>/dev/null || echo "none"); \
	if echo "$$CURRENT_CTX" | grep -q "$(EXPECTED_ACCOUNT_ID)"; then \
		echo "✅ kubectl context: $$CURRENT_CTX"; \
	else \
		echo "⚠️  kubectl context: $$CURRENT_CTX"; \
		echo "   Expected context with account $(EXPECTED_ACCOUNT_ID)"; \
		echo "   Run: kubectl config use-context arn:aws:eks:$(AWS_REGION):$(EXPECTED_ACCOUNT_ID):cluster/$(CLUSTER_NAME)"; \
	fi
	@echo ""
	@echo "Configuration:"
	@echo "   Region:       $(AWS_REGION)"
	@echo "   Cluster:      $(CLUSTER_NAME)"
	@echo "   ECR Registry: $(ECR_REGISTRY)"
	@echo ""

.PHONY: check-account
check-account:
	@CURRENT=$$(AWS_PROFILE=$(AWS_PROFILE) aws sts get-caller-identity --query Account --output text 2>/dev/null); \
	if [ "$$CURRENT" != "$(EXPECTED_ACCOUNT_ID)" ]; then \
		echo "❌ WRONG ACCOUNT! Current: $$CURRENT, Expected: $(EXPECTED_ACCOUNT_ID)"; \
		echo "   Run: export AWS_PROFILE=private"; \
		exit 1; \
	fi

# ============================================================
# Local Development
# ============================================================

.PHONY: dev
dev: ## [local] Start local development with Docker Compose
	docker compose up --build -d
	@echo ""
	@echo "✅ Local environment started!"
	@echo "   Frontend:  http://localhost:3000"
	@echo "   Shop:      http://localhost:3000/shop"
	@echo "   API Docs:  http://localhost:8001/docs (users)"

.PHONY: dev-down
dev-down: ## [local] Stop local development environment
	docker compose down

.PHONY: dev-logs
dev-logs: ## [local] Tail logs from all services
	docker compose logs -f

.PHONY: dev-restart
dev-restart: ## [local] Restart all services
	docker compose restart

.PHONY: dev-rebuild
dev-rebuild: ## [local] Rebuild and restart specific service (usage: make dev-rebuild SVC=orders)
	docker compose up --build -d $(SVC)

.PHONY: dev-db
dev-db: ## [local] Connect to local PostgreSQL
	docker compose exec postgres psql -U root -d postershop

.PHONY: dev-seed
dev-seed: ## [local] Seed all services with sample data
	@echo "Seeding services..."
	curl -s -X POST localhost:8006/seed | jq  # inventory
	curl -s -X POST localhost:8002/seed | jq  # catalog
	@echo "✅ Data seeded"

.PHONY: dev-test
dev-test: ## [local] Run health checks on all services
	@echo "Testing services..."
	@for port in 8001 8002 8003 8004 8005 8006 8007; do \
		status=$$(curl -s -o /dev/null -w "%{http_code}" localhost:$$port/healthz); \
		if [ "$$status" = "200" ]; then \
			echo "  ✅ Port $$port: OK"; \
		else \
			echo "  ❌ Port $$port: FAILED ($$status)"; \
		fi; \
	done

# ============================================================
# Cloud Deployment
# ============================================================

.PHONY: deploy
deploy: check-account ## [deploy] Full production deployment (EKS + RDS + Services)
	chmod +x deploy/full-deploy.sh
	AWS_PROFILE=$(AWS_PROFILE) ./deploy/full-deploy.sh

.PHONY: deploy-dry-run
deploy-dry-run: ## [deploy] Show what would be deployed (dry run)
	chmod +x deploy/full-deploy.sh
	./deploy/full-deploy.sh --dry-run

.PHONY: deploy-services
deploy-services: ## [deploy] Deploy only services (assumes cluster exists)
	chmod +x deploy/deploy.sh
	./deploy/deploy.sh $(NAMESPACE)

.PHONY: cluster-create
cluster-create: check-account ## [cloud] Create EKS cluster (production)
	AWS_PROFILE=$(AWS_PROFILE) eksctl create cluster -f deploy/infrastructure/eksctl-cluster.yaml

.PHONY: cluster-create-dev
cluster-create-dev: ## [cloud] Create EKS cluster (dev - spot instances, cheaper)
	eksctl create cluster -f deploy/infrastructure/eksctl-cluster-dev.yaml

.PHONY: cluster-delete
cluster-delete: ## [cloud] Delete EKS cluster (DESTRUCTIVE!)
	@read -p "Are you sure you want to delete the cluster? [y/N] " confirm; \
	if [ "$$confirm" = "y" ]; then \
		eksctl delete cluster -f deploy/infrastructure/eksctl-cluster.yaml; \
	fi

.PHONY: cluster-kubeconfig
cluster-kubeconfig: ## [cloud] Configure kubectl for the cluster
	aws eks update-kubeconfig --region $(AWS_REGION) --name $(CLUSTER_NAME)

# ============================================================
# Full Deploy / Teardown (Primary Commands)
# ============================================================

.PHONY: cloud-up
cloud-up: check-account ## [cloud deploy] Spin up full cloud infrastructure
	@echo "🚀 Starting full cloud deployment..."
	@echo "   This will create: EKS cluster, RDS, deploy all services"
	@echo "   Estimated time: 25-30 minutes"
	@echo "   Estimated cost: ~\$$3-4/day while running"
	@echo ""
	@read -sp "Enter RDS master password (min 8 chars): " DB_PASS; echo ""; \
	export DB_PASSWORD=$$DB_PASS && \
	AWS_PROFILE=$(AWS_PROFILE) ./deploy/full-deploy.sh

.PHONY: cloud-down
cloud-down: ## [cloud deploy] Tear down all cloud infrastructure (saves costs!)
	@echo "🗑️  Tearing down cloud infrastructure..."
	@echo "   This will DELETE: EKS cluster, RDS"
	@echo "   ECR images will be preserved for next deploy"
	@echo ""
	AWS_PROFILE=$(AWS_PROFILE) ./deploy/teardown.sh

.PHONY: cloud-down-force
cloud-down-force: ## [cloud deploy] Tear down without confirmation
	AWS_PROFILE=$(AWS_PROFILE) ./deploy/teardown.sh --force

.PHONY: cloud-clean-all
cloud-clean-all: ## [cloud deploy] Full cleanup including AWS Secrets Manager
	@echo "⚠️  This will delete EVERYTHING including secrets!"
	@echo "   You'll need to regenerate passwords on next deploy."
	@echo ""
	AWS_PROFILE=$(AWS_PROFILE) ./deploy/teardown.sh --delete-secrets --delete-ecr

.PHONY: cloud-status
cloud-status: ## [cloud deploy] Check status of cloud resources
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║                    Cloud Resource Status                     ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "EKS Clusters:"
	@AWS_PROFILE=$(AWS_PROFILE) eksctl get cluster --region $(AWS_REGION) 2>/dev/null || echo "  No clusters found"
	@echo ""
	@echo "RDS Stacks:"
	@AWS_PROFILE=$(AWS_PROFILE) aws cloudformation describe-stacks --region $(AWS_REGION) \
		--query 'Stacks[?contains(StackName,`postershop`)].{Name:StackName,Status:StackStatus}' \
		--output table 2>/dev/null || echo "  No RDS stacks found"
	@echo ""
	@echo "ECR Repositories:"
	@AWS_PROFILE=$(AWS_PROFILE) aws ecr describe-repositories --region $(AWS_REGION) \
		--query 'repositories[].repositoryName' --output table 2>/dev/null || echo "  No ECR repos found"
	@echo ""
	@echo "AWS Secrets Manager:"
	@AWS_PROFILE=$(AWS_PROFILE) aws secretsmanager list-secrets --region $(AWS_REGION) \
		--filter Key=name,Values=postershop/ \
		--query 'SecretList[].Name' --output table 2>/dev/null || echo "  No postershop secrets found"

.PHONY: rds-create
rds-create: check-account ## [cloud] Create RDS instance
	@read -sp "Enter RDS master password: " DB_PASS; echo ""; \
	VPC=$$(AWS_PROFILE=$(AWS_PROFILE) aws eks describe-cluster --name $(CLUSTER_NAME) --query 'cluster.resourcesVpcConfig.vpcId' --output text); \
	SUBNETS=$$(AWS_PROFILE=$(AWS_PROFILE) aws eks describe-cluster --name $(CLUSTER_NAME) --query 'cluster.resourcesVpcConfig.subnetIds[:2]' --output text | tr '\t' ','); \
	SG=$$(aws eks describe-cluster --name $(CLUSTER_NAME) --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId' --output text); \
	aws cloudformation create-stack \
		--stack-name postershop-rds \
		--template-body file://deploy/infrastructure/rds.yaml \
		--parameters \
			ParameterKey=VpcId,ParameterValue=$$VPC \
			ParameterKey=SubnetIds,ParameterValue="$$SUBNETS" \
			ParameterKey=EKSSecurityGroupId,ParameterValue=$$SG \
			ParameterKey=MasterPassword,ParameterValue=$$DB_PASS

.PHONY: rds-delete
rds-delete: ## [cloud] Delete RDS instance (DESTRUCTIVE!)
	@read -p "Are you sure you want to delete RDS? [y/N] " confirm; \
	if [ "$$confirm" = "y" ]; then \
		aws cloudformation delete-stack --stack-name postershop-rds; \
	fi

.PHONY: rds-init
rds-init: ## [cloud] Initialize RDS schemas and users
	chmod +x deploy/rds/init-all.sh
	./deploy/rds/init-all.sh

# ============================================================
# Docker / ECR
# ============================================================

.PHONY: ecr-login
ecr-login: check-account ## Login to ECR
	AWS_PROFILE=$(AWS_PROFILE) aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)

.PHONY: build-all
build-all: ## Build all Docker images
	@for svc in users catalog orders production logistics inventory payments; do \
		echo "Building $$svc..."; \
		docker build -t $(ECR_REGISTRY)/$$svc:latest services/$$svc; \
	done
	docker build -t $(ECR_REGISTRY)/frontend:latest frontend

.PHONY: push-all
push-all: ecr-login ## Push all images to ECR
	@for svc in users catalog orders production logistics inventory payments frontend; do \
		echo "Pushing $$svc..."; \
		docker push $(ECR_REGISTRY)/$$svc:latest; \
	done

# ============================================================
# Monitoring
# ============================================================

.PHONY: monitoring-install
monitoring-install: ## [cloud] Install Prometheus + Grafana
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
	helm repo update
	kubectl create namespace $(MONITORING_NS) --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
		-n $(MONITORING_NS) \
		-f deploy/monitoring/prometheus-values.yaml \
		--wait --timeout 10m
	kubectl apply -f deploy/monitoring/servicemonitors.yaml -n $(NAMESPACE)
	kubectl apply -f deploy/monitoring/alertrules.yaml -n $(NAMESPACE)
	kubectl apply -f deploy/monitoring/grafana-dashboards-configmap.yaml -n $(MONITORING_NS)

.PHONY: monitoring-port-forward
monitoring-port-forward: ## Port-forward Grafana to localhost:3001
	@echo "Grafana: http://localhost:3001  (admin / postershop-monitoring)"
	kubectl port-forward svc/prometheus-grafana 3001:80 -n $(MONITORING_NS)

# ============================================================
# Kubernetes Utilities
# ============================================================

.PHONY: k-pods
k-pods: ## Show all pods
	kubectl get pods -n $(NAMESPACE)

.PHONY: k-logs
k-logs: ## Tail logs for a service (usage: make k-logs SVC=orders)
	kubectl logs -f -l app=$(SVC) -n $(NAMESPACE)

.PHONY: k-exec
k-exec: ## Exec into a pod (usage: make k-exec SVC=orders)
	kubectl exec -it $$(kubectl get pods -n $(NAMESPACE) -l app=$(SVC) -o jsonpath='{.items[0].metadata.name}') -n $(NAMESPACE) -- /bin/sh

.PHONY: k-restart
k-restart: ## Restart a deployment (usage: make k-restart SVC=orders)
	kubectl rollout restart deployment/$(SVC) -n $(NAMESPACE)

.PHONY: k-status
k-status: ## Show deployment status
	@echo "=== Deployments ==="
	kubectl get deployments -n $(NAMESPACE)
	@echo ""
	@echo "=== Services ==="
	kubectl get svc -n $(NAMESPACE)
	@echo ""
	@echo "=== Ingress ==="
	kubectl get ingress -n $(NAMESPACE)

.PHONY: k-secrets
k-secrets: ## List secrets (names only)
	kubectl get secrets -n $(NAMESPACE)

# ============================================================
# Cleanup
# ============================================================

.PHONY: clean
clean: ## Clean local Docker resources
	docker compose down -v
	docker system prune -f

.PHONY: clean-all
clean-all: ## Clean everything including images
	docker compose down -v
	docker system prune -af

# ============================================================
# Legacy (backwards compatibility)
# ============================================================

.PHONY: bootstrap
bootstrap: cluster-create ## [deprecated] Alias for cluster-create

.PHONY: monitoring
monitoring: monitoring-install ## [deprecated] Alias for monitoring-install

.PHONY: deploy-all
deploy-all: deploy-services ## [deprecated] Alias for deploy-services
