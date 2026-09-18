"""
Designs Service — AI poster studio.

Skeleton in 09-01: health, readiness and metrics only. 09-02 adds the generation
API (POST /generations -> 202 + id, polled by the shop) and the background worker
that claims queued rows and calls the image provider; later plans add print-this,
the memory tiers and the ORDER_PAID subscription.

The image provider (providers.py, IMAGE_PROVIDER env) and the storage backend
(storage.py, STORAGE_BACKEND env) are built lazily through provider()/storage(),
so importing this module never touches the filesystem or the network — unit tests
import it without running the lifespan.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from database import engine
from logger import get_logger, LoggingMiddleware
from metrics import metrics_endpoint, track_metrics, SERVICE_NAME
from providers import get_image_provider
from storage import get_storage

ROOT_PATH = os.getenv("ROOT_PATH", "")

logger = get_logger(__name__)

_provider = None
_storage = None


def provider():
    """The configured ImageProvider, built on first use."""
    global _provider
    if _provider is None:
        _provider = get_image_provider()
    return _provider


def storage():
    """The configured Storage backend, built on first use."""
    global _storage
    if _storage is None:
        _storage = get_storage()
    return _storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info(
        "Designs service starting",
        image_provider=provider().name,
        storage_backend=os.getenv("STORAGE_BACKEND", "local"),
    )
    yield
    logger.info("Shutdown complete")


app = FastAPI(title=f"{SERVICE_NAME} service", lifespan=lifespan, root_path=ROOT_PATH)
app.add_middleware(LoggingMiddleware)
app.middleware("http")(track_metrics)

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

# CORS must be added after LoggingMiddleware so it wraps the outside (runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ============== Health & Metrics ==============

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz")
def readyz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/metrics")
def metrics():
    return metrics_endpoint()
