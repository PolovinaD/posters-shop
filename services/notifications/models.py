from sqlalchemy import Column, String, BigInteger, DateTime
from sqlalchemy.sql import func
from database import Base

SCHEMA_NAME = "notifications_schema"


class ProcessedEvent(Base):
    """Durable consumer-side idempotency: one row per outbox event whose email
    was successfully sent. Keyed by the outbox envelope's event_id."""
    __tablename__ = "processed_events"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    event_id = Column(BigInteger, primary_key=True)          # outbox event_id, natural key
    event_type = Column(String, nullable=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
