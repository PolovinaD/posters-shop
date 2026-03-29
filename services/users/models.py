from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base
from commons import SCHEMA_NAME, TABLE_NAME


class User(Base):
    __tablename__ = TABLE_NAME
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, index=True, unique=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="customer")
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
