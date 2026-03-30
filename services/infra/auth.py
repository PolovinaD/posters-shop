"""
JWT authentication for the infra service.
Pattern: identical to users/auth.py but without DB user lookup.
Requires JWT_SECRET env var. Validates owner role from token payload.
"""
import os
import jwt  # PyJWT
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises 401 on invalid/expired tokens."""
    if not SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET not configured",
        )
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user_claims(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: extracts and validates JWT claims."""
    return decode_token(token)


def require_role(required: str):
    """
    FastAPI dependency factory: validates token AND checks role.
    Usage: Depends(require_role("owner"))
    """
    def _role_dep(claims: dict = Depends(get_current_user_claims)) -> dict:
        if claims.get("role") != required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return claims
    return _role_dep
