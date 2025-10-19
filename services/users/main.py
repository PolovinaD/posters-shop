from fastapi import FastAPI
from sqlalchemy.orm import Session
from database import Base, engine
from metrics import metrics_endpoint

app = FastAPI(title="users service")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "users"}

@app.get("/metrics")
def metrics():
    return metrics_endpoint()


from sqlalchemy import Column, Integer, String
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)



from fastapi import Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import select
from database import get_db
from jose import jwt
import hashlib, os, datetime

from main import app
from main import User

JWT_SECRET = os.getenv("USERS_JWT_SECRET", "devsecret")
ALGO = "HS256"

@app.post("/register")
def register(email: str = Body(...), password: str = Body(...), db: Session = Depends(get_db)):
    ph = hashlib.sha256(password.encode()).hexdigest()
    if db.execute(select(User).where(User.email==email)).scalar_one_or_none():
        raise HTTPException(400, "Email exists")
    u = User(email=email, password_hash=ph)
    db.add(u); db.commit()
    return {"ok": True}

@app.post("/login")
def login(email: str = Body(...), password: str = Body(...), db: Session = Depends(get_db)):
    ph = hashlib.sha256(password.encode()).hexdigest()
    u = db.execute(select(User).where(User.email==email)).scalar_one_or_none()
    if not u or u.password_hash != ph:
        raise HTTPException(401, "Invalid credentials")
    token = jwt.encode(
        {"sub": email, "exp": int((datetime.datetime.utcnow()+datetime.timedelta(hours=1)).timestamp())},
        JWT_SECRET, algorithm=ALGO
    )
    return {"access_token": token, "token_type": "bearer"}
