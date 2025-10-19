from fastapi import FastAPI
from sqlalchemy.orm import Session
from database import Base, engine
from metrics import metrics_endpoint

app = FastAPI(title="catalog service")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "catalog"}

@app.get("/metrics")
def metrics():
    return metrics_endpoint()


from sqlalchemy import Column, Integer, String, Numeric
from database import Base

class Poster(Base):
    __tablename__ = "posters"
    __table_args__ = {"schema": "catalog"}
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    image_url = Column(String, nullable=False)
    base_price = Column(Numeric(10,2), nullable=False)

class Size(Base):
    __tablename__ = "sizes"
    __table_args__ = {"schema": "catalog"}
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False) # e.g., A3, A2
    price_delta = Column(Numeric(10,2), nullable=False, default=0)

class FrameOption(Base):
    __tablename__ = "frame_options"
    __table_args__ = {"schema": "catalog"}
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    extra_price = Column(Numeric(10,2), nullable=False, default=0)



from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy import select
from database import get_db
from main import app
from main import Poster, Size, FrameOption

@app.get("/items")
def list_items(db: Session = Depends(get_db)):
    posters = db.execute(select(Poster)).scalars().all()
    return [{"id": p.id, "title": p.title, "image_url": p.image_url, "base_price": str(p.base_price)} for p in posters]

@app.post("/seed")
def seed(db: Session = Depends(get_db)):
    if not db.execute(select(Poster)).first():
        db.add_all([
            Poster(title="Sunset", image_url="https://example.com/sunset.jpg", base_price=19.99),
            Poster(title="Mountains", image_url="https://example.com/mountains.jpg", base_price=24.99),
        ])
    if not db.execute(select(Size)).first():
        db.add_all([
            Size(name="A3", price_delta=0),
            Size(name="A2", price_delta=5),
            Size(name="A1", price_delta=10),
        ])
    if not db.execute(select(FrameOption)).first():
        db.add_all([
            FrameOption(name="No Frame", extra_price=0),
            FrameOption(name="Black Frame", extra_price=7.5),
            FrameOption(name="Wood Frame", extra_price=12.0),
        ])
    db.commit()
    return {"ok": True}
