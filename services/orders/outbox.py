"""
Outbox Pattern Implementation

The outbox pattern ensures reliable event delivery:
1. When a business operation occurs, write the event to an outbox table in the SAME transaction
2. A background worker polls the outbox and delivers events to subscribers
3. Events are marked as delivered only after successful delivery
4. Failed deliveries are retried with exponential backoff

This guarantees at-least-once delivery even if the service crashes.
"""
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Index, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from database import Base, SessionLocal
from logger import get_logger

logger = get_logger("outbox")

SCHEMA_NAME = "orders_schema"

# Event subscriber URLs - which services listen to which events
EVENT_SUBSCRIBERS = {
    "ORDER_PAID": [
        os.getenv("PRODUCTION_SERVICE_URL", "http://production:8000") + "/events/order-paid"
    ],
    "ORDER_CANCELLED": [
        os.getenv("PRODUCTION_SERVICE_URL", "http://production:8000") + "/events/order-cancelled"
    ],
}

# Retry configuration
MAX_RETRIES = 5
RETRY_DELAYS = [5, 15, 60, 300, 900]  # seconds: 5s, 15s, 1m, 5m, 15m
DELIVERY_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class OutboxEvent(Base):
    """Outbox table for reliable event delivery."""
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_pending", "delivered_at", "retry_after"),
        Index("ix_outbox_event_type", "event_type"),
        {"schema": SCHEMA_NAME}
    )

    id = Column(Integer, primary_key=True)
    event_type = Column(String(100), nullable=False)
    aggregate_type = Column(String(100), nullable=False)  # e.g., "order"
    aggregate_id = Column(String(100), nullable=False)    # e.g., order_id
    payload = Column(Text, nullable=False)                # JSON payload
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    retry_after = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)


def emit_event(
    db: Session,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict
) -> OutboxEvent:
    """
    Write an event to the outbox table.
    
    IMPORTANT: Call this within the same transaction as your business logic.
    The event will only be persisted if the transaction commits.
    """
    event = OutboxEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload=json.dumps(payload)
    )
    db.add(event)
    # Don't commit here - let the caller control the transaction
    return event


async def deliver_event(event: OutboxEvent) -> tuple[bool, Optional[str]]:
    """
    Attempt to deliver an event to all subscribers.
    
    Returns (success, error_message)
    """
    subscribers = EVENT_SUBSCRIBERS.get(event.event_type, [])
    
    if not subscribers:
        # No subscribers - consider it delivered
        return True, None
    
    payload = {
        "event_id": event.id,
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "payload": json.loads(event.payload),
        "created_at": event.created_at.isoformat() if event.created_at else None
    }
    
    errors = []
    async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
        for subscriber_url in subscribers:
            try:
                response = await client.post(subscriber_url, json=payload)
                if response.status_code >= 400:
                    errors.append(f"{subscriber_url}: HTTP {response.status_code}")
            except httpx.RequestError as e:
                errors.append(f"{subscriber_url}: {str(e)}")
    
    if errors:
        return False, "; ".join(errors)
    
    return True, None


async def process_outbox_events(db: Session) -> int:
    """
    Process pending outbox events.
    
    Returns the number of events processed.
    """
    now = datetime.now(timezone.utc)
    
    # Find events that are:
    # 1. Not yet delivered
    # 2. Ready for retry (retry_after is null or in the past)
    # 3. Haven't exceeded max retries
    pending_events = db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.delivered_at.is_(None))
        .where(OutboxEvent.retry_count < MAX_RETRIES)
        .where(
            (OutboxEvent.retry_after.is_(None)) | 
            (OutboxEvent.retry_after <= now)
        )
        .order_by(OutboxEvent.created_at)
        .limit(10)
        .with_for_update(skip_locked=True)
    ).scalars().all()
    
    processed = 0
    for event in pending_events:
        success, error = await deliver_event(event)
        
        if success:
            event.delivered_at = now
            logger.info("Event delivered", event_id=event.id, event_type=event.event_type, aggregate_id=event.aggregate_id)
        else:
            event.retry_count += 1
            event.last_error = error
            
            if event.retry_count < MAX_RETRIES:
                delay = RETRY_DELAYS[min(event.retry_count - 1, len(RETRY_DELAYS) - 1)]
                event.retry_after = now + timedelta(seconds=delay)
                logger.warning("Event delivery failed, will retry", event_id=event.id, retry_count=event.retry_count, retry_delay_sec=delay, error=error)
            else:
                logger.error("Event delivery failed permanently", event_id=event.id, retry_count=event.retry_count, error=error)
        
        processed += 1
    
    if processed > 0:
        db.commit()
    
    return processed


async def outbox_worker(poll_interval: float = 2.0):
    """
    Background worker that polls and delivers outbox events.
    
    Args:
        poll_interval: How often to poll for new events (seconds)
    """
    logger.info("Worker started", poll_interval=poll_interval)
    
    while True:
        try:
            with SessionLocal() as db:
                processed = await process_outbox_events(db)
                if processed > 0:
                    logger.debug("Batch processed", events_count=processed)
        except Exception as e:
            logger.error("Worker error", error=str(e), exc_info=True)
        
        await asyncio.sleep(poll_interval)


def get_pending_event_count(db: Session) -> int:
    """Get count of undelivered events."""
    return db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.delivered_at.is_(None))
        .where(OutboxEvent.retry_count < MAX_RETRIES)
    ).scalars().all().__len__()


def get_failed_event_count(db: Session) -> int:
    """Get count of permanently failed events."""
    return db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.delivered_at.is_(None))
        .where(OutboxEvent.retry_count >= MAX_RETRIES)
    ).scalars().all().__len__()

