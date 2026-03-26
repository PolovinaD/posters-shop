from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

SCHEMA_NAME = "orders_schema"


class OrderStatus:
    """Order state machine states."""
    CREATED = "created"           # Order created, items added
    RESERVED = "reserved"         # Stock reserved in inventory
    PAID = "paid"                 # Payment successful
    PRODUCING = "producing"       # In production
    SHIPPED = "shipped"           # Shipped to customer
    DELIVERED = "delivered"       # Delivered to customer
    CANCELLED = "cancelled"       # Order cancelled
    FAILED = "failed"             # Order failed (payment/production)

    # Valid state transitions
    TRANSITIONS = {
        CREATED: [RESERVED, CANCELLED, FAILED],
        RESERVED: [PAID, CANCELLED, FAILED],  # Can cancel while reserved
        PAID: [PRODUCING, CANCELLED],          # Can cancel before production starts
        PRODUCING: [SHIPPED, FAILED],          # Cannot cancel during production
        SHIPPED: [DELIVERED],
        DELIVERED: [],                         # Terminal state
        CANCELLED: [],                         # Terminal state
        FAILED: [],                            # Terminal state
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, [])

    @classmethod
    def can_cancel(cls, status: str) -> bool:
        return cls.CANCELLED in cls.TRANSITIONS.get(status, [])


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_customer_email", "customer_email"),
        Index("ix_orders_status", "status"),
        {"schema": SCHEMA_NAME}
    )

    id = Column(Integer, primary_key=True)
    customer_email = Column(String, nullable=False)
    status = Column(String, nullable=False, default=OrderStatus.CREATED)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Payment fields
    checkout_session_id = Column(String, nullable=True)  # Stripe checkout session
    payment_intent_id = Column(String, nullable=True)    # Stripe payment intent
    
    # Relationships
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey(f"{SCHEMA_NAME}.orders.id"), nullable=False)
    sku = Column(String, nullable=False)  # Reference to inventory SKU
    name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(10, 2), nullable=False)
    
    # Relationship
    order = relationship("Order", back_populates="items")

