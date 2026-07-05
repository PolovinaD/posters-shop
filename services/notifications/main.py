"""
Notifications Service — transactional email on order-lifecycle events.

Stateless FastAPI service (no database, no migrations) that subscribes to the
orders outbox and "sends" an email for each order-lifecycle event:
ORDER_PAID, ORDER_SHIPPED, ORDER_DELIVERED, ORDER_CANCELLED.

Email transport is pluggable (see providers.py): the logging provider is used
for local dev (no AWS creds), the SES provider for production (via IRSA).
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from logger import get_logger, LoggingMiddleware
from metrics import (
    metrics_endpoint, track_metrics, SERVICE_NAME,
    EMAILS_SENT, EMAIL_SEND_FAILURES,
)
from providers import get_provider

ROOT_PATH = os.getenv("ROOT_PATH", "")

logger = get_logger(__name__)


class OutboxEventPayload(BaseModel):
    """Incoming event from the orders outbox worker."""
    event_id: int
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict
    created_at: str | None = None


# Instantiate the email provider once at module load (logging by default).
provider = get_provider()

# In-memory idempotency guard. NOTE: this resets on pod restart; combined with
# the at-least-once outbox delivery this means a rare duplicate email is
# possible after a restart — acceptable given the stateless-mock precedent
# (payments) and the low blast radius of a duplicate transactional email.
_processed_event_ids: set[int] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info(
        "Notifications service starting",
        email_provider=os.getenv("EMAIL_PROVIDER", "logging"),
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
    # Stateless service — no DB to check, always ready once the process is up.
    return {"status": "ready"}


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


# ============== Email Rendering ==============

def _format_items(payload: dict) -> str:
    """Render an optional item list into plain-text lines (empty string if none)."""
    items = payload.get("items") or []
    lines = []
    for item in items:
        name = item.get("name", item.get("sku", "item"))
        qty = item.get("quantity", 1)
        lines.append(f"  - {name} x{qty}")
    return ("\n".join(lines) + "\n") if lines else ""


def render_email(event_type: str, payload: dict) -> tuple[str, str]:
    """Build (subject, plain-text body) for an order-lifecycle event."""
    order_id = payload.get("order_id", "?")
    total = payload.get("total_amount")
    items_block = _format_items(payload)

    if event_type == "ORDER_PAID":
        subject = f"Your PosterShop order #{order_id} is confirmed"
        body = (
            f"Thank you for your order!\n\n"
            f"We've received payment for order #{order_id}.\n"
        )
        if items_block:
            body += f"\nItems:\n{items_block}"
        if total is not None:
            body += f"\nTotal: {total}\n"
        body += "\nWe'll let you know when it ships.\n"
        return subject, body

    if event_type == "ORDER_SHIPPED":
        subject = f"Your PosterShop order #{order_id} has shipped"
        body = (
            f"Good news — order #{order_id} is on its way!\n"
        )
        if items_block:
            body += f"\nItems:\n{items_block}"
        body += "\nYou'll get another note when it's delivered.\n"
        return subject, body

    if event_type == "ORDER_DELIVERED":
        subject = f"Your PosterShop order #{order_id} was delivered"
        body = (
            f"Order #{order_id} has been delivered. We hope you love your posters!\n"
        )
        if items_block:
            body += f"\nItems:\n{items_block}"
        return subject, body

    if event_type == "ORDER_CANCELLED":
        subject = f"Your PosterShop order #{order_id} was cancelled"
        reason = payload.get("reason", "cancelled")
        body = (
            f"Order #{order_id} has been cancelled ({reason}).\n"
            f"Any reserved stock has been released. If this was unexpected, "
            f"please contact support.\n"
        )
        return subject, body

    # Fallback — should not happen given the fixed set of handlers.
    subject = f"Update on your PosterShop order #{order_id}"
    body = f"There is an update on order #{order_id}.\n"
    return subject, body


# ============== Event Processing ==============

def _process(event: OutboxEventPayload, event_type: str) -> dict:
    """Idempotently send the email for one order-lifecycle event."""
    if event.event_id in _processed_event_ids:
        logger.info(
            "Event already processed (idempotent)",
            event_id=event.event_id, event_type=event_type,
        )
        return {"status": "already_processed", "event_id": event.event_id}

    to = event.payload.get("customer_email")
    if not to:
        # Nothing to send and nothing to retry — do NOT 500.
        logger.warning(
            "No customer_email in event payload, skipping",
            event_id=event.event_id, event_type=event_type,
        )
        return {"status": "skipped", "reason": "no_customer_email"}

    subject, body = render_email(event_type, event.payload)

    try:
        provider.send(to, subject, body)
    except Exception as e:
        EMAIL_SEND_FAILURES.labels(event_type=event_type).inc()
        logger.error(
            "Email send failed",
            event_id=event.event_id, event_type=event_type, error=str(e),
            exc_info=True,
        )
        # Signal the outbox to retry; do NOT mark as processed.
        raise HTTPException(status_code=503, detail="email send failed")

    _processed_event_ids.add(event.event_id)
    EMAILS_SENT.labels(event_type=event_type, status="sent").inc()
    logger.info(
        "Email sent",
        event_id=event.event_id, event_type=event_type, to=to,
    )
    return {"status": "sent", "event_id": event.event_id}


# ============== Event Listeners (Outbox Pattern) ==============

@app.post("/events/order-paid")
def handle_order_paid(event: OutboxEventPayload):
    return _process(event, "ORDER_PAID")


@app.post("/events/order-shipped")
def handle_order_shipped(event: OutboxEventPayload):
    return _process(event, "ORDER_SHIPPED")


@app.post("/events/order-delivered")
def handle_order_delivered(event: OutboxEventPayload):
    return _process(event, "ORDER_DELIVERED")


@app.post("/events/order-cancelled")
def handle_order_cancelled(event: OutboxEventPayload):
    return _process(event, "ORDER_CANCELLED")
