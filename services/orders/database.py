from typing import Generator
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL")
# Connection budget: pool_size=3, max_overflow=5 → max 8 connections per pod.
# At HPA max scale (3 pods): 3 × 8 = 24 orders connections.
# Other 5 services × 1 pod × 10 = 50 connections.
# Total: 74 < 87 usable connections on RDS db.t3.micro.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=5,
    pool_timeout=30,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
