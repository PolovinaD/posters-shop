import os
from fastapi import FastAPI, Depends, HTTPException, status, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from logger import get_logger, LoggingMiddleware
from commons import SERVICE_NAME, UserRole

logger = get_logger(__name__)
from database import get_db
from models import User
from schemas import RegisterIn, LoginIn, UserOut, TokenOut, ChangePasswordRequest, ChangeRoleRequest, AdminCreateUser
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    get_current_user_claims,
    require_role,
)
from init_db import init_db
from metrics import metrics_endpoint, track_metrics

ROOT_PATH = os.getenv("ROOT_PATH", "")
app = FastAPI(title=f"{SERVICE_NAME} service", root_path=ROOT_PATH)

app.add_middleware(LoggingMiddleware)
app.middleware("http")(track_metrics)

@app.on_event("startup")
def startup():
    init_db()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


@app.post("/register", status_code=200)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role="customer"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return Response(status_code=status.HTTP_200_OK)


@app.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(sub=user.email, role=user.role)
    return TokenOut(access_token=token)


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
