from fastapi import FastAPI
from sqlalchemy.orm import Session
from database import Base, engine
from metrics import metrics_endpoint

app = FastAPI(title="production service")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "production"}

@app.get("/metrics")
def metrics():
    return metrics_endpoint()


from sqlalchemy import Column, Integer, String
from database import Base

class Material(Base):
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    stock = Column(Integer, nullable=False, default=0)

class Job(Base):
    __tablename__ = "production_jobs"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="queued")



from fastapi import Depends, Body
from sqlalchemy.orm import Session
from sqlalchemy import select
from database import get_db
from main import app
from main import Material, Job

@app.post("/jobs")
def create_job(order_id: int = Body(...), db: Session = Depends(get_db)):
    j = Job(order_id=order_id, status="queued")
    db.add(j); db.commit()
    return {"job_id": j.id}

@app.post("/jobs/{job_id}/process")
def process_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        return {"error": "not found"}
    # CPU load for HPA demo
    x = 0
    for i in range(20_000_00):
        x += i*i
    j.status = "done"
    db.commit()
    return {"job_id": j.id, "status": j.status}

@app.get("/materials")
def list_materials(db: Session = Depends(get_db)):
    mats = db.execute(select(Material)).scalars().all()
    return [{"id": m.id, "name": m.name, "stock": m.stock} for m in mats]
