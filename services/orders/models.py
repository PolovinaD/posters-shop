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

    # Shipping address — the authoritative record of what the customer agreed to
    # at checkout. Nullable: orders created before this column existed have none.
    shipping_recipient_name = Column(String, nullable=True)
    shipping_street = Column(String, nullable=True)
    shipping_city = Column(String, nullable=True)
    shipping_postal_code = Column(String, nullable=True)
    shipping_country = Column(String, nullable=True)
    shipping_phone = Column(String, nullable=True)
    
    # Relationships
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    @property
    def shipping_address(self):
        """Nested view of the shipping_* columns; None for pre-address orders."""
        # Guard on ALL six: OrderOut validates this against the full
        # ShippingAddress model, so a half-populated row would raise
        # ValidationError and turn GET /orders/{id} into a 500. Unreachable
        # through the API today (all six are written together from one
        # validated model) — this is cheap insurance for hand-edited rows.
        if not all((
            self.shipping_recipient_name, self.shipping_street, self.shipping_city,
            self.shipping_postal_code, self.shipping_country, self.shipping_phone,
        )):
            return None
        return {
            "recipient_name": self.shipping_recipient_name,
            "street": self.shipping_street,
            "city": self.shipping_city,
            "postal_code": self.shipping_postal_code,
            "country": self.shipping_country,
            "phone": self.shipping_phone,
        }


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

