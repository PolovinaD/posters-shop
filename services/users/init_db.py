from sqlalchemy import select
from database import Base, engine, SessionLocal, init_schema
from models import User
from auth import hash_password
from main import SERVICE_NAME

SCHEMA_NAME = SERVICE_NAME
TABLE_NAME = SERVICE_NAME

DEFAULT_OWNER_EMAIL = "admin@postershop.com"
DEFAULT_OWNER_PASS = "admin1234"


def init_db():
    init_schema(SCHEMA_NAME)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        owner_exists = db.execute(select(User).where(User.role == "owner")).scalar_one_or_none()
        if not owner_exists:
            owner = User(
                email=DEFAULT_OWNER_EMAIL,
                password_hash=hash_password(DEFAULT_OWNER_PASS),
                role="owner"
            )
            db.add(owner)
            db.commit()
            print(f"Default owner created: {DEFAULT_OWNER_EMAIL} / {DEFAULT_OWNER_PASS}")