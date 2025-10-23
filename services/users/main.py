from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from commons import SERVICE_NAME
from database import get_db
from models import User
from schemas import RegisterIn, LoginIn, UserOut, TokenOut, ChangePasswordRequest
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user_claims,
    require_role,
)
from init_db import init_db
from metrics import metrics_endpoint, track_metrics

app = FastAPI(title=f"{SERVICE_NAME} service")

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


@app.post("/register", response_model=UserOut, status_code=201)
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
    return user


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
    current_user: User = Depends(get_current_user_claims),
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

@app.get("/me", response_model=UserOut)
def me(claims=Depends(get_current_user_claims), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == claims["sub"])).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/admin/ping")
def admin_ping(_=Depends(require_role("owner"))):
    return {"message": "pong"}