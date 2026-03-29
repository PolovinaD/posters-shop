import os
import hashlib
from datetime import datetime, UTC
from fastapi import FastAPI, Depends, HTTPException, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, delete, text
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from logger import get_logger, LoggingMiddleware
from commons import SERVICE_NAME, UserRole

logger = get_logger(__name__)
from database import get_db, engine
from models import User, RefreshToken
from schemas import RegisterIn, LoginIn, UserOut, TokenOut, ChangePasswordRequest, ChangeRoleRequest, AdminCreateUser, RefreshIn
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_current_user_claims,
    require_role,
)
from init_db import init_db
from metrics import metrics_endpoint, track_metrics

ROOT_PATH = os.getenv("ROOT_PATH", "")
app = FastAPI(title=f"{SERVICE_NAME} service", root_path=ROOT_PATH)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(LoggingMiddleware)
app.middleware("http")(track_metrics)

CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

# CORS must be added after LoggingMiddleware so it wraps the outside (runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz")
def readyz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


@app.post("/register", response_model=TokenOut)
@limiter.limit("10/minute")
def register(request: Request, payload: RegisterIn, db: Session = Depends(get_db)):
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role="customer",
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    db.add(user)
    db.flush()  # flush to get user.id for FK

    access_token = create_access_token(sub=user.email, role=user.role)
    refresh_token = create_refresh_token(user.id, db)
    db.commit()
    return TokenOut(access_token=access_token, refresh_token=refresh_token)


@app.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(request: Request, payload: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(sub=user.email, role=user.role)
    refresh_token = create_refresh_token(user.id, db)
    db.commit()
    return TokenOut(access_token=access_token, refresh_token=refresh_token)


@app.post("/auth/refresh", response_model=TokenOut)
def refresh_token(payload: RefreshIn, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()

    # SELECT FOR UPDATE to prevent concurrent rotation race
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == token_hash
    ).with_for_update()
    db_token = db.execute(stmt).scalar_one_or_none()

    if not db_token or db_token.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.get(User, db_token.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Rotate: delete old, create new (token rotation)
    db.delete(db_token)
    new_raw_token = create_refresh_token(user.id, db)
    new_access_token = create_access_token(sub=user.email, role=user.role)
    db.commit()
    return TokenOut(access_token=new_access_token, refresh_token=new_raw_token)


@app.post("/auth/logout", status_code=200)
def logout(
    payload: RefreshIn,
    db: Session = Depends(get_db),
    _claims=Depends(get_current_user_claims),
):
    token_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()
    db_token = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).scalar_one_or_none()

    if db_token:
        db.delete(db_token)
        db.commit()
    return {"message": "Logged out"}


@app.post("/auth/logout-all", status_code=200)
def logout_all(
    db: Session = Depends(get_db),
    claims=Depends(get_current_user_claims),
):
    user = db.execute(select(User).where(User.email == claims["sub"])).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    db.commit()
    return {"message": "All sessions revoked"}


@app.post("/users/me/password", status_code=200)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Old password is incorrect."
        )

    new_hash = hash_password(payload.new_password)

    current_user.password_hash = new_hash
    db.add(current_user)
    db.commit()

    return {"message": "Password updated successfully"}


@app.get("/users/me", response_model=UserOut)
def me(claims=Depends(get_current_user_claims), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == claims["sub"])).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.put("/users/{user_id}/role")
def change_user_role(
    user_id: int,
    payload: ChangeRoleRequest,
    db: Session = Depends(get_db),
    _=Depends(require_role(UserRole.OWNER)),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = payload.new_role
    db.commit()
    return Response(status_code=status.HTTP_200_OK)


@app.get("/admin/ping")
def admin_ping(_=Depends(require_role(UserRole.OWNER))):
    return {"message": "pong"}


# --- Admin User Management ---

@app.get("/admin/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _=Depends(require_role(UserRole.OWNER)),
):
    """List all users (owner only)."""
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return users


@app.post("/admin/users", response_model=UserOut, status_code=201)
def create_user(
    payload: AdminCreateUser,
    db: Session = Depends(get_db),
    _=Depends(require_role(UserRole.OWNER)),
):
    """Create a new user with a specific role (owner only)."""
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.delete("/admin/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    claims=Depends(require_role(UserRole.OWNER)),
):
    """Delete a user (owner only). Cannot delete yourself."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Prevent deleting yourself
    if user.email == claims.get("sub"):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/admin/users/{user_id}/reset-password", status_code=200)
def reset_user_password(
    user_id: int,
    new_password: str,
    db: Session = Depends(get_db),
    _=Depends(require_role(UserRole.OWNER)),
):
    """Reset a user's password (owner only)."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"message": "Password reset successfully"}
