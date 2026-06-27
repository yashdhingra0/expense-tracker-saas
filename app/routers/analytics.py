"""Read-only analytics endpoints, all scoped to the current tenant."""

from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import analytics
from ..db import get_db
from ..deps import current_user
from ..models import User

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _month(month):
    return month or date.today().strftime("%Y-%m")


@router.get("/summary")
def summary(month: Optional[str] = Query(None), db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    return analytics.summary(db, user.id, _month(month), float(user.monthly_budget))


@router.get("/categories")
def categories(month: Optional[str] = Query(None), db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    return analytics.categories(db, user.id, _month(month))


@router.get("/people")
def people(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return analytics.people(db, user.id)


@router.get("/months")
def months(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return analytics.month_series(db, user.id)


@router.get("/budgets")
def budgets(month: Optional[str] = Query(None), db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    return analytics.budgets_usage(db, user.id, _month(month))


@router.get("/insights")
def insights(month: Optional[str] = Query(None), db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    return analytics.insights(db, user.id, _month(month), float(user.monthly_budget))
