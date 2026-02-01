from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.sql import func
from database import Base

SCHEMA_NAME = "production"


class JobStatus:
    """Production job state machine."""
    QUEUED = "queued"           # Job created, waiting for processing
    PROCESSING = "processing"   # Currently being processed
    COMPLETED = "completed"     # Successfully completed
    FAILED = "failed"           # Failed during processing

    TRANSITIONS = {
        QUEUED: [PROCESSING, FAILED],
        PROCESSING: [COMPLETED, FAILED],
        COMPLETED: [],  # Terminal
        FAILED: [QUEUED],  # Can retry
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, [])


class Job(Base):
    """Production job for an order."""
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_order_id", "order_id"),
        Index("ix_jobs_status", "status"),
        {"schema": SCHEMA_NAME}
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False, unique=True)  # One job per order
    status = Column(String, nullable=False, default=JobStatus.QUEUED)
    items_json = Column(Text, nullable=True)  # JSON of items to produce
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_time_ms = Column(Integer, nullable=True)

