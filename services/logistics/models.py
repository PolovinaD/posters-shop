from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from database import Base

SCHEMA_NAME = "logistics_schema"


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = {"schema": SCHEMA_NAME}
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="preparing")
    tracking = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Delivery copy, written once at shipment creation (event-carried state
    # transfer). Schema-per-service means logistics cannot read orders_schema,
    # and a courier read must not depend on the orders service being up.
    recipient_name = Column(String, nullable=True)
    street = Column(String, nullable=True)
    city = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True)
    recipient_phone = Column(String, nullable=True)

    # Who bound which wallet on pick-up (dispatched -> in_transit), and when.
    # courier_id is the caller's JWT `sub` -- the user's email, which is what
    # users mints (services/users/main.py:94) -- and NULL when the unattended
    # worker bound LOGISTICS_DEFAULT_COURIER_WALLET. courier_wallet is the
    # address actually sent to orders; orders keeps its own snapshot of it.
    courier_id = Column(String, nullable=True)
    courier_wallet = Column(String(42), nullable=True)
    courier_bound_at = Column(DateTime, nullable=True)
