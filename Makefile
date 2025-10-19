SHELL := /bin/bash

bootstrap:
	eksctl create cluster --name shop --region eu-north-1 --nodes 2 --node-type t3.large --with-oidc

monitoring:
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
	helm repo add grafana https://grafana.github.io/helm-charts || true
	kubectl create ns monitoring --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install monitor prometheus-community/kube-prometheus-stack -n monitoring
	helm upgrade --install loki grafana/loki-stack -n monitoring --set grafana.enabled=false

deploy-all:
	helm upgrade --install users       deploy/charts/users       -n shop --create-namespace
	helm upgrade --install catalog     deploy/charts/catalog     -n shop
	helm upgrade --install orders      deploy/charts/orders      -n shop
	helm upgrade --install production  deploy/charts/production  -n shop
	helm upgrade --install logistics   deploy/charts/logistics   -n shop
