from sqlalchemy import Column, Integer, String
from database import Base
from init_db import SCHEMA_NAME, TABLE_NAME


class User(Base):
    __tablename__ = TABLE_NAME
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, index=True, unique=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="customer")
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
