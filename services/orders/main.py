from fastapi import FastAPI
from sqlalchemy.orm import Session
from database import Base, engine
from metrics import metrics_endpoint

app = FastAPI(title="orders service")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "orders"}

@app.get("/metrics")
def metrics():
    return metrics_endpoint()


from sqlalchemy import Column, Integer, String, Numeric, ForeignKey
from database import Base

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": "orders"}
    id = Column(Integer, primary_key=True)
    status = Column(String, nullable=False, default="created")
    customer_email = Column(String, nullable=False)

class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = {"schema": "orders"}
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    poster_id = Column(Integer, nullable=False)
    size = Column(String, nullable=False)
    frame = Column(String, nullable=True)
    price = Column(Numeric(10,2), nullable=False, default=0)



from fastapi import Depends, Body
from sqlalchemy.orm import Session
from sqlalchemy import select
from database import get_db
from main import app
from main import Order, OrderItem

@app.post("/orders")
def create_order(
    customer_email: str = Body(...),
    items: list[dict] = Body(...),
    db: Session = Depends(get_db),
):
    o = Order(customer_email=customer_email, status="created")
    db.add(o); db.flush()
    for it in items:
        db.add(OrderItem(order_id=o.id, poster_id=it["poster_id"], size=it["size"], frame=it.get("frame"), price=it.get("price", 0)))
    db.commit()
    return {"order_id": o.id, "status": o.status}

@app.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if not o:
        return {"error": "not found"}
    items = db.execute(select(OrderItem).where(OrderItem.order_id==o.id)).scalars().all()
    return {"id": o.id, "status": o.status, "items": [ {"id": i.id, "poster_id": i.poster_id, "size": i.size, "frame": i.frame, "price": str(i.price)} for i in items ]}
