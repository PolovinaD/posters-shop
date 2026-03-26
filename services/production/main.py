import os
import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Body

ROOT_PATH = os.getenv("ROOT_PATH", "")
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database import Base, engine, get_db, SessionLocal
from models import Job, JobStatus, SCHEMA_NAME
from schemas import JobCreate, JobOut, JobSummary, ProcessResult
from logger import get_logger, LoggingMiddleware

logger = get_logger(__name__)


class OutboxEventPayload(BaseModel):
    """Incoming event from outbox worker."""
    event_id: int
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict
    created_at: str | None = None
from metrics import (
    metrics_endpoint, track_metrics, SERVICE_NAME,
    JOBS_CREATED, JOBS_COMPLETED, JOBS_BY_STATUS,
    JOB_PROCESSING_TIME, JOBS_IN_QUEUE
)
import orders_client

# Background worker control
background_task = None
WORKER_POLL_INTERVAL = 5  # seconds


def simulate_production_work(items_json: str) -> int:
    """
    Simulate production work. CPU-intensive for HPA demo.
    Returns processing time in milliseconds.
    """
    start = time.time()
    
    # Parse items to determine work amount
    items = json.loads(items_json) if items_json else []
    total_quantity = sum(item.get("quantity", 1) for item in items)
    
    # CPU-intensive work scaled by quantity
    # Each item adds ~100ms of work
    iterations = max(500_000, total_quantity * 500_000)
    x = 0
    for i in range(iterations):
        x += i * i % 1000
    
    return int((time.time() - start) * 1000)


async def process_job(job: Job, db: Session) -> bool:
    """Process a single job. Returns True on success."""
    try:
        # Mark as processing
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        
        # Notify orders service that production started
        await orders_client.notify_order_producing(job.order_id)
        
        # Do the actual work (CPU-intensive)
        processing_time = simulate_production_work(job.items_json)
        
        # Mark as completed
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.processing_time_ms = processing_time
        db.commit()
        
        # Update metrics
        JOBS_COMPLETED.labels(status="completed").inc()
        JOB_PROCESSING_TIME.observe(processing_time / 1000)
        
        logger.info("Job completed", job_id=job.id, order_id=job.order_id, processing_time_ms=processing_time)
        
        # Notify orders service and create shipment
        await orders_client.notify_order_shipped(job.order_id)
        
        return True
        
    except Exception as e:
        job.status = JobStatus.FAILED
        job.error_message = str(e)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        
        JOBS_COMPLETED.labels(status="failed").inc()
        logger.error("Job failed", job_id=job.id, order_id=job.order_id, error=str(e), exc_info=True)
        
        return False


async def job_worker():
    """Background worker that processes queued jobs."""
    logger.info("Job worker started", poll_interval=WORKER_POLL_INTERVAL)
    
    while True:
        try:
            with SessionLocal() as db:
                # Find next queued job (FIFO)
                job = db.execute(
                    select(Job)
                    .where(Job.status == JobStatus.QUEUED)
                    .order_by(Job.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                
                if job:
                    await process_job(job, db)
                    # Update queue metric
                    queue_count = db.execute(
                        select(Job).where(Job.status == JobStatus.QUEUED)
                    ).scalars().all()
                    JOBS_IN_QUEUE.set(len(queue_count))
                    
        except Exception as e:
            logger.error("Worker error", error=str(e), exc_info=True)
        
        await asyncio.sleep(WORKER_POLL_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup - migrations are handled by Alembic
    logger.info("Production service starting, migrations managed by Alembic")
    
    # Start background worker
    global background_task
    background_task = asyncio.create_task(job_worker())
    
    yield
    
    # Shutdown
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutdown complete")


app = FastAPI(title=f"{SERVICE_NAME} service", lifespan=lifespan, root_path=ROOT_PATH)
app.add_middleware(LoggingMiddleware)
app.middleware("http")(track_metrics)


# ============== Health & Metrics ==============

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


# ============== Job Management ==============

@app.post("/jobs", response_model=JobOut, status_code=201)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    """
    Create a new production job for an order.
    Called by orders service when order is paid.
    """
    # Check if job already exists for this order
    existing = db.execute(
        select(Job).where(Job.order_id == payload.order_id)
    ).scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Job already exists for order {payload.order_id}"
        )
    
    # Create job
    items_json = json.dumps([item.model_dump() for item in payload.items]) if payload.items else None
    
    job = Job(
        order_id=payload.order_id,
        status=JobStatus.QUEUED,
        items_json=items_json
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Update metrics
    JOBS_CREATED.inc()
    JOBS_IN_QUEUE.inc()
    
    logger.info("Job created", job_id=job.id, order_id=payload.order_id)
    
    return job


@app.get("/jobs", response_model=list[JobSummary])
def list_jobs(
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """List jobs with optional status filter."""
    query = select(Job)
    
    if status:
        query = query.where(Job.status == status)
    
    query = query.order_by(Job.created_at.desc()).offset(skip).limit(limit)
    jobs = db.execute(query).scalars().all()
    
    return jobs


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get job by ID."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/order/{order_id}", response_model=JobOut)
def get_job_by_order(order_id: int, db: Session = Depends(get_db)):
    """Get job by order ID."""
    job = db.execute(
        select(Job).where(Job.order_id == order_id)
    ).scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail=f"No job found for order {order_id}")
    return job


@app.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: int, db: Session = Depends(get_db)):
    """Retry a failed job."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != JobStatus.FAILED:
        raise HTTPException(
            status_code=400,
            detail=f"Can only retry failed jobs. Current status: {job.status}"
        )
    
    job.status = JobStatus.QUEUED
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.processing_time_ms = None
    db.commit()
    db.refresh(job)
    
    JOBS_IN_QUEUE.inc()
    
    return job


# ============== Event Listeners (Outbox Pattern) ==============

@app.post("/events/order-paid")
def handle_order_paid(event: OutboxEventPayload, db: Session = Depends(get_db)):
    """
    Handle ORDER_PAID event from orders service outbox.
    
    This endpoint is called by the orders outbox worker when an order is paid.
    It creates a production job for the order.
    """
    logger.info("Received ORDER_PAID event", event_id=event.event_id, aggregate_id=event.aggregate_id)
    
    order_id = event.payload.get("order_id")
    items = event.payload.get("items", [])
    
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order_id in event payload")
    
    # Check if job already exists (idempotency)
    existing = db.execute(
        select(Job).where(Job.order_id == order_id)
    ).scalar_one_or_none()
    
    if existing:
        logger.info("Job already exists, skipping (idempotent)", order_id=order_id, job_id=existing.id)
        return {"status": "already_exists", "job_id": existing.id}
    
    # Create the production job
    items_json = json.dumps(items) if items else None
    
    job = Job(
        order_id=order_id,
        status=JobStatus.QUEUED,
        items_json=items_json
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Update metrics
    JOBS_CREATED.inc()
    JOBS_IN_QUEUE.inc()
    
    logger.info("Job created via outbox event", job_id=job.id, order_id=order_id, event_id=event.event_id)
    
    return {"status": "created", "job_id": job.id}


@app.post("/events/order-cancelled")
def handle_order_cancelled(event: OutboxEventPayload, db: Session = Depends(get_db)):
    """
    Handle ORDER_CANCELLED event from orders service outbox.
    
    If a job exists and hasn't started, cancel it.
    """
    logger.info("Received ORDER_CANCELLED event", event_id=event.event_id, aggregate_id=event.aggregate_id)
    
    order_id = event.payload.get("order_id")
    
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order_id in event payload")
    
    # Find job for this order
    job = db.execute(
        select(Job).where(Job.order_id == order_id)
    ).scalar_one_or_none()
    
    if not job:
        logger.debug("No job found for cancelled order", order_id=order_id)
        return {"status": "no_job"}
    
    if job.status == JobStatus.QUEUED:
        job.status = JobStatus.FAILED
        job.error_message = "Order cancelled"
        db.commit()
        JOBS_IN_QUEUE.dec()
        logger.info("Job cancelled", job_id=job.id, order_id=order_id)
        return {"status": "cancelled", "job_id": job.id}
    else:
        logger.info("Job already processing, cannot cancel", job_id=job.id, order_id=order_id, status=job.status)
        return {"status": "already_processing", "job_id": job.id}


# ============== Stats ==============

@app.get("/jobs/stats/summary")
def job_stats(db: Session = Depends(get_db)):
    """Get job statistics."""
    all_jobs = db.execute(select(Job)).scalars().all()
    
    stats = {
        "total": len(all_jobs),
        "by_status": {},
        "avg_processing_time_ms": 0
    }
    
    processing_times = []
    for job in all_jobs:
        stats["by_status"][job.status] = stats["by_status"].get(job.status, 0) + 1
        if job.processing_time_ms:
            processing_times.append(job.processing_time_ms)
        
        # Update Prometheus gauge
        JOBS_BY_STATUS.labels(status=job.status).set(stats["by_status"][job.status])
    
    if processing_times:
        stats["avg_processing_time_ms"] = sum(processing_times) // len(processing_times)
    
    return stats
