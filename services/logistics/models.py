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
