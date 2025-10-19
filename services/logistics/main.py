from fastapi import FastAPI
from sqlalchemy.orm import Session
from database import Base, engine
from metrics import metrics_endpoint

app = FastAPI(title="logistics service")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "logistics"}

@app.get("/metrics")
def metrics():
    return metrics_endpoint()


from sqlalchemy import Column, Integer, String
from database import Base

class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = {"schema": "logistics"}
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="preparing")
    tracking = Column(String, nullable=True)



from fastapi import Depends, Body
from sqlalchemy.orm import Session
from database import get_db
from main import app
from main import Shipment

@app.post("/ship")
def create_shipment(order_id: int = Body(...), db: Session = Depends(get_db)):
    s = Shipment(order_id=order_id, status="dispatched", tracking=f"TRK-{order_id:06d}")
    db.add(s); db.commit()
    return {"shipment_id": s.id, "tracking": s.tracking}

@app.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    s = db.get(Shipment, shipment_id)
    if not s:
        return {"error": "not found"}
    return {"id": s.id, "order_id": s.order_id, "status": s.status, "tracking": s.tracking}
