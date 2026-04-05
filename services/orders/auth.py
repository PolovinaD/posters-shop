import os
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET environment variable is required")

ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login", auto_error=False)


def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


def get_current_user_claims(token: str = Depends(oauth2_scheme)):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return decode_token(token)


def require_courier_or_admin(claims: dict = Depends(get_current_user_claims)):
    """Require courier or owner role for shipment operations."""
    role = claims.get("role")
    if role not in ("courier", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only couriers or admins can update shipments"
        )
    return claims


def optional_auth(token: str = Depends(oauth2_scheme)):
    """Optional authentication - returns claims if authenticated, None otherwise."""
    if not token:
        return None
    try:
        return decode_token(token)
    except HTTPException:
        return None
