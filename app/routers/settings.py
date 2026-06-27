"""Per-user settings: currency, monthly budget, category caps."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User, Budget
from ..schemas import SettingsIn

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    caps = db.execute(select(Budget).where(Budget.user_id == user.id)).scalars().all()
    return {"currency": user.currency, "monthly_budget": float(user.monthly_budget),
            "budgets": {b.category: float(b.monthly_cap) for b in caps}}


@router.put("")
def update_settings(body: SettingsIn, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    if body.currency is not None:
        user.currency = body.currency
    if body.monthly_budget is not None:
        user.monthly_budget = body.monthly_budget
    if body.budgets:
        existing = {b.category: b for b in
                    db.execute(select(Budget).where(Budget.user_id == user.id)).scalars()}
        for cat, cap in body.budgets.items():
            if cat in existing:
                existing[cat].monthly_cap = cap
            else:
                db.add(Budget(user_id=user.id, category=cat, monthly_cap=cap))
    db.commit()
    return {"ok": True}
