"""Signup / login / logout / me."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, SESSION_COOKIE
from ..models import User, Budget, DEFAULT_BUDGETS
from ..schemas import SignupIn, LoginIn, UserOut
from ..security import hash_password, verify_password, make_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(resp: Response, user_id: str):
    resp.set_cookie(
        SESSION_COOKIE, make_session(user_id),
        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
        # secure=True,   # enable behind HTTPS in production
    )


@router.post("/signup", response_model=UserOut)
def signup(body: SignupIn, resp: Response, db: Session = Depends(get_db)):
    exists = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    for cat, cap in DEFAULT_BUDGETS.items():
        db.add(Budget(user_id=user.id, category=cat, monthly_cap=cap))
    db.commit()
    _set_cookie(resp, user.id)
    return UserOut(id=user.id, email=user.email, plan=user.plan,
                   currency=user.currency, monthly_budget=float(user.monthly_budget))


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, resp: Response, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This email address is not registered. Please create an account.")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect password. Please try again.")
    _set_cookie(resp, user.id)
    return UserOut(id=user.id, email=user.email, plan=user.plan,
                   currency=user.currency, monthly_budget=float(user.monthly_budget))


@router.post("/logout")
def logout(resp: Response):
    resp.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return UserOut(id=user.id, email=user.email, plan=user.plan,
                   currency=user.currency, monthly_budget=float(user.monthly_budget))
