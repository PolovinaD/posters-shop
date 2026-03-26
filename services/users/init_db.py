from sqlalchemy import select
from database import SessionLocal
from models import User
from auth import hash_password
from commons import UserRole
from logger import get_logger

logger = get_logger(__name__)

DEFAULT_OWNER_EMAIL = "admin@postershop.com"
DEFAULT_OWNER_PASS = "admin1234"


def init_db():
    logger.info("Database tables managed by Alembic migrations")

    with SessionLocal() as db:
        owner_exists = db.execute(select(User).where(User.role == UserRole.OWNER)).scalar_one_or_none()
        if not owner_exists:
            owner = User(
                email=DEFAULT_OWNER_EMAIL,
                password_hash=hash_password(DEFAULT_OWNER_PASS),
                role=UserRole.OWNER
            )
            db.add(owner)
            db.commit()
            print(f"Default owner created: {DEFAULT_OWNER_EMAIL} / {DEFAULT_OWNER_PASS}")