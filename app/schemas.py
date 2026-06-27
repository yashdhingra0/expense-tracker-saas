"""Pydantic request/response shapes."""

import re
from typing import Optional, Dict
from datetime import date

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    email: str
    password: str = Field(min_length=6)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v.lower()


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    plan: str
    currency: str
    monthly_budget: float


class MessageIn(BaseModel):
    text: str  # a plain-English line, same as a Telegram message


class TxnOut(BaseModel):
    id: int
    date: date
    category: str
    amount: float
    note: str
    type: str
    person: Optional[str] = None
    source: str


class TxnEdit(BaseModel):
    amount: Optional[float] = None
    category: Optional[str] = None
    note: Optional[str] = None


class BotConnectIn(BaseModel):
    token: str


class SettingsIn(BaseModel):
    currency: Optional[str] = None
    monthly_budget: Optional[float] = None
    budgets: Optional[Dict[str, float]] = None
