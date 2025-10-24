from sqlalchemy import select
from database import Base, engine, SessionLocal, init_schema
from models import User
from auth import hash_password
from commons import SCHEMA_NAME, UserRole

DEFAULT_OWNER_EMAIL = "admin@postershop.com"
DEFAULT_OWNER_PASS = "admin1234"


def init_db():
    init_schema(SCHEMA_NAME)
    Base.metadata.create_all(bind=engine)

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