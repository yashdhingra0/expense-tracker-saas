"""Multi-tenant data model. Every domain row carries user_id (tenant)."""

from typing import Optional
import uuid
from datetime import datetime, date as dtdate

from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Date, DateTime, ForeignKey,
    LargeBinary, Boolean, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    plan: Mapped[str] = mapped_column(String(20), default="free")
    currency: Mapped[str] = mapped_column(String(8), default="₹")
    monthly_budget: Mapped[float] = mapped_column(Numeric(14, 2), default=50000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bots: Mapped[list["TelegramBot"]] = relationship(back_populates="user")


class TelegramBot(Base):
    __tablename__ = "telegram_bots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    bot_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    bot_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    routing_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=_uuid)
    webhook_secret: Mapped[str] = mapped_column(String(64), default=_uuid)
    token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)  # ENCRYPTED
    status: Mapped[str] = mapped_column(String(20), default="pending")
    linked_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="bots")


class Txn(Base):
    __tablename__ = "txns"
    __table_args__ = (
        UniqueConstraint("user_id", "tg_update_id", name="uq_user_update"),
        Index("ix_txns_user_date", "user_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dtdate] = mapped_column(Date, default=dtdate.today)
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    note: Mapped[str] = mapped_column(String(255), default="")
    type: Mapped[str] = mapped_column(String(20), default="expense")
    person: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    tg_update_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category", name="uq_user_cat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    monthly_cap: Mapped[float] = mapped_column(Numeric(14, 2), default=0)


DEFAULT_BUDGETS = {
    "travel": 5000, "food": 8000, "groceries": 6000, "clothes": 4000,
    "rent": 18000, "bills": 4000, "luxuries": 5000, "investments": 10000,
    "health": 3000, "education": 3000, "other": 3000,
}
