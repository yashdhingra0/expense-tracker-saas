"""Transactions: add from a message, list, edit, delete — all tenant-scoped."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import parser
from ..db import get_db
from ..deps import current_user
from ..models import User, Txn
from ..schemas import MessageIn, TxnOut, TxnEdit

router = APIRouter(prefix="/txns", tags=["txns"])


def _to_out(r: Txn) -> TxnOut:
    return TxnOut(id=r.id, date=r.date, category=r.category, amount=float(r.amount),
                  note=r.note, type=r.type, person=r.person, source=r.source)


@router.post("", response_model=TxnOut)
def add_from_message(body: MessageIn, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    """Log an entry from a plain-English line (same engine as the bot)."""
    p = parser.parse(body.text)
    if p["amount"] is None:
        raise HTTPException(422, "Couldn't find an amount in that message.")
    row = Txn(user_id=user.id, category=p["category"], amount=p["amount"],
              note=p["note"], type=p["type"], person=p["person"], source="manual")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get("", response_model=list[TxnOut])
def list_txns(month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
              limit: int = 200, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    stmt = select(Txn).where(Txn.user_id == user.id).order_by(Txn.date.desc(), Txn.id.desc())
    rows = db.execute(stmt).scalars().all()
    if month:
        rows = [r for r in rows if r.date.strftime("%Y-%m") == month]
    return [_to_out(r) for r in rows[:limit]]


@router.patch("/{txn_id}", response_model=TxnOut)
def edit_txn(txn_id: int, body: TxnEdit, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    row = db.get(Txn, txn_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Not found")
    if body.amount is not None:
        row.amount = body.amount
    if body.category is not None:
        row.category = body.category
    if body.note is not None:
        row.note = body.note
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/{txn_id}")
def delete_txn(txn_id: int, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    row = db.get(Txn, txn_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
