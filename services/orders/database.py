from typing import Generator
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL")
# Connection budget (RDS db.t3.micro, ~87 usable). Per pod = pool_size + max_overflow;
# replica ranges come from the HPA manifests, not from replicaCount.
#   orders      2-5 pods x 8   -> steady 15, peak 40   (charts/orders/templates/hpa.yaml)
#   production  1-5 pods x 10  -> steady 25, peak 50   (charts/production/templates/hpa.yaml)
#   5 others    1 pod   x 10   -> steady 25, peak 50
# At max replicas: steady 65 fits, peak 140 does not. Reaching the peak needs both
# autoscalers saturated at once and is untested. readyz reuses this pool and Alembic
# uses NullPool, so neither adds to the total.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=5,
    # bulkhead.py admits at most pool_size + max_overflow requests at once, so a wait
    # here is a fault, not a burst: fail in 5 s instead of parking a thread for 30 s.
    pool_timeout=5,
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


# ---- runtime tripwire -------------------------------------------------------
import asyncio
from sqlalchemy import event
from logger import get_logger

_log = get_logger("database")


@event.listens_for(engine, "before_cursor_execute")
def _warn_if_on_event_loop(conn, cursor, statement, parameters, context, executemany):
    """Tripwire for the 2026-09-18 defect: SQL issued from the uvicorn event loop
    thread blocks every other request and /healthz. Every statement must come from a
    threadpool thread (a `def` route, run_in_threadpool, asyncio.to_thread)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # worker thread: the normal case
    _log.warning("SQL executed on the event loop", statement=statement[:120])
