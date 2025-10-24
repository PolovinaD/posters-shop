import os
from database import get_db
from datetime import datetime, timedelta, UTC
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from models import User
from sqlalchemy.orm import Session
from passlib.context import CryptContext

SECRET_KEY = os.getenv("JWT_SECRET", "change_me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(sub: str, role: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": sub, "role": role, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def get_current_user_claims(token: str = Depends(oauth2_scheme)):
    return decode_token(token)


def get_current_user(
    claims: dict = Depends(get_current_user_claims),
    db: Session = Depends(get_db)
) -> User:
    user_id = claims.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload (missing 'sub')"
        )

    user = db.query(User).filter(User.email == str(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


def require_role(required: str):
    def _role_dep(claims=Depends(get_current_user_claims)):
        if claims.get("role") != required:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return claims
    return _role_dep