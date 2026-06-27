"""Shared FastAPI dependencies — current authenticated tenant."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import read_session

SESSION_COOKIE = "session"


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = read_session(request.cookies.get(SESSION_COOKIE))
    user = db.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user
