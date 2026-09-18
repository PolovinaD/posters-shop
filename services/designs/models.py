"""SQLAlchemy models for the designs service (designs_schema).

Generation statuses: queued -> generating -> ready | failed. `retry_after` and
`attempts` drive the worker's backoff: a queued row is only claimed once
`retry_after` is null or in the past, and a provider failure bumps `attempts`
until DESIGNS_MAX_ATTEMPTS flips the row to failed. `purchases` (written by the
ORDER_PAID handler) feeds the style profile alongside the customer's prompts;
`processed_events` is the outbox dedup table (notifications precedent).
"""
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, DateTime, JSON, Index, UniqueConstraint,
)
from sqlalchemy.sql import func
from database import Base

SCHEMA_NAME = "designs_schema"


class Generation(Base):
    """One prompt -> one image job. `image_key` lands in the Storage backend."""
    __tablename__ = "generations"
    __table_args__ = (
        Index("ix_generations_customer_created", "customer_email", "created_at"),
        Index("ix_generations_status_retry", "status", "retry_after"),
        {"schema": SCHEMA_NAME},
    )

    id = Column(Integer, primary_key=True)
    customer_email = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    effective_prompt = Column(Text, nullable=False)
    personalise = Column(Boolean, nullable=False, default=False, server_default="false")
    provider = Column(String, nullable=False, default="fake")
    params = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="queued")  # queued | generating | ready | failed
    failure_reason = Column(Text, nullable=True)
    image_key = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    retry_after = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    purchased_at = Column(DateTime(timezone=True), nullable=True)
    catalog_product_sku = Column(String, nullable=True)


class SavedPrompt(Base):
    """A prompt the customer chose to keep for reuse."""
    __tablename__ = "saved_prompts"
    __table_args__ = (
        Index("ix_saved_prompts_customer", "customer_email"),
        {"schema": SCHEMA_NAME},
    )

    id = Column(Integer, primary_key=True)
    customer_email = Column(String, nullable=False)
    title = Column(String(120), nullable=False)
    prompt = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StyleProfile(Base):
    """Per-customer style summary derived from prompts + purchases; `stale`
    marks it for a lazy refresh on the next personalised generation."""
    __tablename__ = "style_profiles"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    customer_email = Column(String, primary_key=True)
    summary = Column(Text, nullable=True)
    prompt_count = Column(Integer, nullable=False, default=0, server_default="0")
    purchase_count = Column(Integer, nullable=False, default=0, server_default="0")
    stale = Column(Boolean, nullable=False, default=True, server_default="true")
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Purchase(Base):
    """One row per (order, sku) from ORDER_PAID events: what the customer bought."""
    __tablename__ = "purchases"
    __table_args__ = (
        Index("ix_purchases_customer", "customer_email"),
        UniqueConstraint("order_id", "sku", name="uq_purchases_order_sku"),
        {"schema": SCHEMA_NAME},
    )

    id = Column(Integer, primary_key=True)
    customer_email = Column(String, nullable=False)
    order_id = Column(Integer, nullable=False)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    purchased_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProcessedEvent(Base):
    """Durable consumer-side idempotency: one row per outbox event handled.
    Keyed by the outbox envelope's event_id."""
    __tablename__ = "processed_events"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    event_id = Column(BigInteger, primary_key=True, autoincrement=False)  # outbox event_id, natural key
    event_type = Column(String, nullable=False)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
