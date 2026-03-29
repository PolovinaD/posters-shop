"""
Infrastructure Management Service

Provides an API for managing Kubernetes resources:
- List/scale deployments
- View pod status and logs
- Monitor resource usage
- Manage HPA settings

For local development, uses mock data.
In cluster, uses the Kubernetes Python client.
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from logger import get_logger, LoggingMiddleware

logger = get_logger(__name__)

# Check if running in Kubernetes
IN_CLUSTER = os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token')
NAMESPACE = os.getenv('NAMESPACE', 'postershop')
ROOT_PATH = os.getenv("ROOT_PATH", "")

# Kubernetes client (only import if in cluster)
k8s_client = None
k8s_apps_v1 = None
k8s_core_v1 = None
k8s_autoscaling_v1 = None
k8s_custom_api = None

if IN_CLUSTER:
    from kubernetes import client, config
    config.load_incluster_config()
    k8s_client = client
    k8s_apps_v1 = client.AppsV1Api()
    k8s_core_v1 = client.CoreV1Api()
    k8s_autoscaling_v1 = client.AutoscalingV1Api()
    k8s_custom_api = client.CustomObjectsApi()


# ============== Models ==============

class DeploymentInfo(BaseModel):
    name: str
    replicas: int
    available: int
    ready: int
    cpu_usage: Optional[float] = None  # millicores
    memory_usage: Optional[float] = None  # MB
    status: str  # healthy, degraded, unhealthy
    image: Optional[str] = None
    created_at: Optional[str] = None


class PodInfo(BaseModel):
    name: str
    status: str
    ready: bool
    restarts: int
    age: str
    node: Optional[str] = None
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None


class HPAInfo(BaseModel):
    name: str
    min_replicas: int
    max_replicas: int
    current_replicas: int
    target_cpu: int
    current_cpu: Optional[int] = None


class ScaleRequest(BaseModel):
    replicas: int


class HPAUpdateRequest(BaseModel):
    min_replicas: Optional[int] = None
    max_replicas: Optional[int] = None
    target_cpu: Optional[int] = None


# ============== Mock Data (for local development) ==============

MOCK_DEPLOYMENTS = {
    "users": {"replicas": 1, "available": 1, "cpu": 45, "memory": 128},
    "catalog": {"replicas": 1, "available": 1, "cpu": 32, "memory": 96},
    "orders": {"replicas": 1, "available": 1, "cpu": 78, "memory": 156},
    "production": {"replicas": 2, "available": 2, "cpu": 120, "memory": 245},
    "logistics": {"replicas": 1, "available": 1, "cpu": 28, "memory": 88},
    "inventory": {"replicas": 1, "available": 1, "cpu": 55, "memory": 112},
    "payments": {"replicas": 1, "available": 1, "cpu": 22, "memory": 72},
    "frontend": {"replicas": 2, "available": 2, "cpu": 15, "memory": 64},
}

MOCK_HPA = {
    "production": {"min": 1, "max": 5, "current": 2, "target_cpu": 70, "current_cpu": 60},
}


# ============== App Setup ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting infrastructure service", in_cluster=IN_CLUSTER, namespace=NAMESPACE)
    yield
    logger.info("Shutting down")


app = FastAPI(title="Infrastructure Service", lifespan=lifespan, root_path=ROOT_PATH)

app.add_middleware(LoggingMiddleware)

CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

# CORS must be added after LoggingMiddleware so it wraps the outside (runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ============== Health ==============

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "infra", "in_cluster": IN_CLUSTER}


# ============== Deployments ==============

@app.get("/deployments", response_model=List[DeploymentInfo])
def list_deployments():
    """List all deployments with status and resource usage."""
    if not IN_CLUSTER:
        # Return mock data for local development
        result = []
        for name, data in MOCK_DEPLOYMENTS.items():
            status = "healthy" if data["available"] == data["replicas"] else "degraded"
            if data["available"] == 0:
                status = "unhealthy"
            result.append(DeploymentInfo(
                name=name,
                replicas=data["replicas"],
                available=data["available"],
                ready=data["available"],
                cpu_usage=data["cpu"],
                memory_usage=data["memory"],
                status=status,
                image=f"${{ECR_REGISTRY}}/{name}:latest",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
        return result
    
    # Real Kubernetes API
    deployments = k8s_apps_v1.list_namespaced_deployment(namespace=NAMESPACE)
    
    # Fetch pod metrics and group by deployment
    pod_metrics = get_pod_metrics()
    pods = k8s_core_v1.list_namespaced_pod(namespace=NAMESPACE)
    
    # Map pods to deployments and aggregate metrics
    deployment_metrics = {}
    for pod in pods.items:
        # Get deployment name from labels
        labels = pod.metadata.labels or {}
        dep_name = labels.get("app")
        if not dep_name:
            continue
        
        if dep_name not in deployment_metrics:
            deployment_metrics[dep_name] = {"cpu": 0, "memory": 0}
        
        metrics = pod_metrics.get(pod.metadata.name, {})
        deployment_metrics[dep_name]["cpu"] += metrics.get("cpu", 0)
        deployment_metrics[dep_name]["memory"] += metrics.get("memory", 0)
    
    result = []
    
    for dep in deployments.items:
        spec = dep.spec
        status = dep.status
        
        available = status.available_replicas or 0
        ready = status.ready_replicas or 0
        replicas = spec.replicas or 1
        
        if available == replicas:
            health = "healthy"
        elif available > 0:
            health = "degraded"
        else:
            health = "unhealthy"
        
        # Get image from first container
        image = None
        if spec.template.spec.containers:
            image = spec.template.spec.containers[0].image
        
        # Get aggregated metrics for this deployment
        metrics = deployment_metrics.get(dep.metadata.name, {})
        
        result.append(DeploymentInfo(
            name=dep.metadata.name,
            replicas=replicas,
            available=available,
            ready=ready,
            cpu_usage=round(metrics.get("cpu", 0), 1) or None,
            memory_usage=round(metrics.get("memory", 0), 1) or None,
            status=health,
            image=image,
            created_at=dep.metadata.creation_timestamp.isoformat() if dep.metadata.creation_timestamp else None,
        ))
    
    return result


@app.get("/deployments/{name}", response_model=DeploymentInfo)
def get_deployment(name: str):
    """Get details for a specific deployment."""
    deployments = list_deployments()
    for dep in deployments:
        if dep.name == name:
            return dep
    raise HTTPException(status_code=404, detail=f"Deployment '{name}' not found")


@app.post("/deployments/{name}/scale")
def scale_deployment(name: str, req: ScaleRequest):
    """Scale a deployment to the specified number of replicas."""
    if req.replicas < 0 or req.replicas > 10:
        raise HTTPException(status_code=400, detail="Replicas must be between 0 and 10")
    
    if not IN_CLUSTER:
        # Mock scaling
        if name not in MOCK_DEPLOYMENTS:
            raise HTTPException(status_code=404, detail=f"Deployment '{name}' not found")
        MOCK_DEPLOYMENTS[name]["replicas"] = req.replicas
        MOCK_DEPLOYMENTS[name]["available"] = req.replicas
        return {"message": f"Scaled {name} to {req.replicas} replicas", "replicas": req.replicas}
    
    # Real Kubernetes API
    try:
        k8s_apps_v1.patch_namespaced_deployment_scale(
            name=name,
            namespace=NAMESPACE,
            body={"spec": {"replicas": req.replicas}}
        )
        return {"message": f"Scaled {name} to {req.replicas} replicas", "replicas": req.replicas}
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Deployment '{name}' not found")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/deployments/{name}/restart")
def restart_deployment(name: str):
    """Restart a deployment by triggering a rollout."""
    if not IN_CLUSTER:
        # Mock restart
        if name not in MOCK_DEPLOYMENTS:
            raise HTTPException(status_code=404, detail=f"Deployment '{name}' not found")
        return {"message": f"Restarted {name}", "status": "rolling"}
    
    # Real Kubernetes API - patch with annotation to trigger rollout
    try:
        now = datetime.now(timezone.utc).isoformat()
        k8s_apps_v1.patch_namespaced_deployment(
            name=name,
            namespace=NAMESPACE,
            body={
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": now
                            }
                        }
                    }
                }
            }
        )
        return {"message": f"Restarted {name}", "status": "rolling"}
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Deployment '{name}' not found")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Metrics Helper ==============

def get_pod_metrics() -> dict:
    """Fetch pod metrics from the metrics API."""
    if not IN_CLUSTER or not k8s_custom_api:
        return {}
    
    try:
        metrics = k8s_custom_api.list_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=NAMESPACE,
            plural="pods"
        )
        
        result = {}
        for item in metrics.get("items", []):
            pod_name = item["metadata"]["name"]
            cpu_total = 0
            memory_total = 0
            
            for container in item.get("containers", []):
                cpu_str = container.get("usage", {}).get("cpu", "0")
                mem_str = container.get("usage", {}).get("memory", "0")
                
                # Parse CPU (e.g., "100m" = 100 millicores, "1" = 1000 millicores)
                if cpu_str.endswith("n"):
                    cpu_total += int(cpu_str[:-1]) / 1_000_000  # nanocores to millicores
                elif cpu_str.endswith("m"):
                    cpu_total += int(cpu_str[:-1])
                else:
                    cpu_total += int(cpu_str) * 1000
                
                # Parse memory (e.g., "128Mi", "1Gi", "1000Ki")
                if mem_str.endswith("Ki"):
                    memory_total += int(mem_str[:-2]) / 1024  # KiB to MiB
                elif mem_str.endswith("Mi"):
                    memory_total += int(mem_str[:-2])
                elif mem_str.endswith("Gi"):
                    memory_total += int(mem_str[:-2]) * 1024
                else:
                    memory_total += int(mem_str) / (1024 * 1024)  # bytes to MiB
            
            result[pod_name] = {"cpu": round(cpu_total, 1), "memory": round(memory_total, 1)}
        
        return result
    except Exception as e:
        logger.warning("Failed to fetch pod metrics", error=str(e))
        return {}


# ============== Pods ==============

@app.get("/pods", response_model=List[PodInfo])
def list_pods(deployment: Optional[str] = None):
    """List all pods, optionally filtered by deployment."""
    if not IN_CLUSTER:
        # Mock pods
        result = []
        for name, data in MOCK_DEPLOYMENTS.items():
            if deployment and name != deployment:
                continue
            for i in range(data["replicas"]):
                result.append(PodInfo(
                    name=f"{name}-{i+1}-abc12",
                    status="Running",
                    ready=True,
                    restarts=0,
                    age="2h",
                    node="worker-1",
                    cpu_usage=data["cpu"] / data["replicas"],
                    memory_usage=data["memory"] / data["replicas"],
                ))
        return result
    
    # Real Kubernetes API
    label_selector = f"app={deployment}" if deployment else None
    pods = k8s_core_v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=label_selector)
    
    # Fetch metrics
    pod_metrics = get_pod_metrics()
    
    result = []
    for pod in pods.items:
        status = pod.status
        
        # Calculate age
        if pod.metadata.creation_timestamp:
            age_delta = datetime.now(timezone.utc) - pod.metadata.creation_timestamp.replace(tzinfo=timezone.utc)
            if age_delta.days > 0:
                age = f"{age_delta.days}d"
            elif age_delta.seconds > 3600:
                age = f"{age_delta.seconds // 3600}h"
            else:
                age = f"{age_delta.seconds // 60}m"
        else:
            age = "unknown"
        
        # Check if ready
        ready = False
        if status.conditions:
            for cond in status.conditions:
                if cond.type == "Ready" and cond.status == "True":
                    ready = True
                    break
        
        # Count restarts
        restarts = 0
        if status.container_statuses:
            for cs in status.container_statuses:
                restarts += cs.restart_count
        
        # Get metrics for this pod
        metrics = pod_metrics.get(pod.metadata.name, {})
        
        result.append(PodInfo(
            name=pod.metadata.name,
            status=status.phase,
            ready=ready,
            restarts=restarts,
            age=age,
            node=spec.node_name if (spec := pod.spec) else None,
            cpu_usage=metrics.get("cpu"),
            memory_usage=metrics.get("memory"),
        ))
    
    return result


@app.delete("/pods/{name}")
def delete_pod(name: str):
    """Delete a pod (it will be recreated by the deployment)."""
    if not IN_CLUSTER:
        return {"message": f"Deleted pod {name}"}
    
    try:
        k8s_core_v1.delete_namespaced_pod(name=name, namespace=NAMESPACE)
        return {"message": f"Deleted pod {name}"}
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Pod '{name}' not found")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pods/{name}/logs")
def get_pod_logs(
    name: str,
    tail: int = Query(100, ge=1, le=1000),
    container: Optional[str] = None
):
    """Get logs from a pod."""
    if not IN_CLUSTER:
        # Mock logs
        lines = [
            f"[{datetime.now().isoformat()}] INFO: Service started",
            f"[{datetime.now().isoformat()}] INFO: Handling request GET /healthz",
            f"[{datetime.now().isoformat()}] INFO: Response 200 in 5ms",
        ] * (tail // 3 + 1)
        return {"logs": "\n".join(lines[:tail])}
    
    try:
        logs = k8s_core_v1.read_namespaced_pod_log(
            name=name,
            namespace=NAMESPACE,
            container=container,
            tail_lines=tail,
        )
        return {"logs": logs}
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Pod '{name}' not found")
        raise HTTPException(status_code=500, detail=str(e))


# ============== HPA ==============

@app.get("/hpa", response_model=List[HPAInfo])
def list_hpa():
    """List all HorizontalPodAutoscalers."""
    if not IN_CLUSTER:
        # Mock HPA
        return [
            HPAInfo(
                name=name,
                min_replicas=data["min"],
                max_replicas=data["max"],
                current_replicas=data["current"],
                target_cpu=data["target_cpu"],
                current_cpu=data["current_cpu"],
            )
            for name, data in MOCK_HPA.items()
        ]
    
    # Real Kubernetes API
    hpas = k8s_autoscaling_v1.list_namespaced_horizontal_pod_autoscaler(namespace=NAMESPACE)
    result = []
    
    for hpa in hpas.items:
        current_cpu = None
        if hpa.status.current_cpu_utilization_percentage:
            current_cpu = hpa.status.current_cpu_utilization_percentage
        
        result.append(HPAInfo(
            name=hpa.metadata.name,
            min_replicas=hpa.spec.min_replicas or 1,
            max_replicas=hpa.spec.max_replicas,
            current_replicas=hpa.status.current_replicas,
            target_cpu=hpa.spec.target_cpu_utilization_percentage or 80,
            current_cpu=current_cpu,
        ))
    
    return result


@app.patch("/hpa/{name}")
def update_hpa(name: str, req: HPAUpdateRequest):
    """Update HPA settings."""
    if not IN_CLUSTER:
        if name not in MOCK_HPA:
            raise HTTPException(status_code=404, detail=f"HPA '{name}' not found")
        if req.min_replicas is not None:
            MOCK_HPA[name]["min"] = req.min_replicas
        if req.max_replicas is not None:
            MOCK_HPA[name]["max"] = req.max_replicas
        if req.target_cpu is not None:
            MOCK_HPA[name]["target_cpu"] = req.target_cpu
        return {"message": f"Updated HPA {name}", "settings": MOCK_HPA[name]}
    
    # Build patch
    patch = {"spec": {}}
    if req.min_replicas is not None:
        patch["spec"]["minReplicas"] = req.min_replicas
    if req.max_replicas is not None:
        patch["spec"]["maxReplicas"] = req.max_replicas
    if req.target_cpu is not None:
        patch["spec"]["targetCPUUtilizationPercentage"] = req.target_cpu
    
    try:
        k8s_autoscaling_v1.patch_namespaced_horizontal_pod_autoscaler(
            name=name,
            namespace=NAMESPACE,
            body=patch
        )
        return {"message": f"Updated HPA {name}"}
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"HPA '{name}' not found")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Cluster Info ==============

@app.get("/cluster")
def get_cluster_info():
    """Get cluster overview information."""
    if not IN_CLUSTER:
        return {
            "namespace": NAMESPACE,
            "in_cluster": False,
            "node_count": 2,
            "total_pods": sum(d["replicas"] for d in MOCK_DEPLOYMENTS.values()),
            "total_deployments": len(MOCK_DEPLOYMENTS),
            "mode": "local-development",
        }
    
    # Get node count
    nodes = k8s_core_v1.list_node()
    
    # Get pod count
    pods = k8s_core_v1.list_namespaced_pod(namespace=NAMESPACE)
    
    # Get deployment count
    deployments = k8s_apps_v1.list_namespaced_deployment(namespace=NAMESPACE)
    
    return {
        "namespace": NAMESPACE,
        "in_cluster": True,
        "node_count": len(nodes.items),
        "total_pods": len(pods.items),
        "total_deployments": len(deployments.items),
        "mode": "kubernetes",
    }


# ============== WebSocket for live logs ==============

@app.websocket("/ws/logs/{pod_name}")
async def websocket_logs(websocket: WebSocket, pod_name: str):
    """Stream logs from a pod via WebSocket."""
    await websocket.accept()
    
    if not IN_CLUSTER:
        # Mock streaming logs
        try:
            i = 0
            while True:
                await websocket.send_text(f"[{datetime.now().isoformat()}] Log line {i}\n")
                i += 1
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            pass
        return
    
    # Real log streaming would use watch API
    try:
        # For simplicity, poll every second
        while True:
            try:
                logs = k8s_core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=NAMESPACE,
                    tail_lines=10,
                    since_seconds=2,
                )
                if logs:
                    await websocket.send_text(logs)
            except Exception:
                pass
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass

