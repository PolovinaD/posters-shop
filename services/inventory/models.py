from sqlalchemy import Column, Integer, String, DateTime, Index
from sqlalchemy.sql import func
from database import Base

SCHEMA_NAME = "inventory"


class Stock(Base):
    """Tracks available and reserved quantities per SKU."""
    __tablename__ = "stock"
    __table_args__ = (
        Index("ix_stock_sku", "sku", unique=True),
        {"schema": SCHEMA_NAME}
    )

    id = Column(Integer, primary_key=True)
    sku = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    available = Column(Integer, nullable=False, default=0)
    reserved = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Reservation(Base):
    """Tracks stock reservations with TTL for automatic expiration."""
    __tablename__ = "reservations"
    __table_args__ = (
        Index("ix_reservations_expires_at", "expires_at"),
        Index("ix_reservations_order_id", "order_id"),
        {"schema": SCHEMA_NAME}
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False)
    sku = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="active")  # active, released, expired, committed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    released_at = Column(DateTime(timezone=True), nullable=True)

