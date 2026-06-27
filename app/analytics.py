"""Tenant-scoped aggregations: summary, categories, IOU balances, insights."""

from calendar import monthrange
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Txn, Budget

IOU_TYPES = ("lent", "borrowed", "repaid_to_me", "repaid_by_me")


def _rows(db: Session, user_id: str):
    return db.execute(select(Txn).where(Txn.user_id == user_id)
                      .order_by(Txn.date.asc(), Txn.id.asc())).scalars().all()


def month_rows(rows, month):
    return [r for r in rows if r.date.strftime("%Y-%m") == month]


def summary(db, user_id, month, monthly_budget):
    rows = month_rows(_rows(db, user_id), month)
    spent = float(sum(r.amount for r in rows if r.type == "expense"))
    income = float(sum(r.amount for r in rows if r.type == "income"))
    y, m = map(int, month.split("-"))
    dim = monthrange(y, m)[1]
    today = date.today()
    is_cur = month == today.strftime("%Y-%m")
    day_now = today.day if is_cur else dim
    per_day = spent / day_now if day_now else 0
    projection = per_day * dim
    return {
        "month": month, "spent": round(spent, 2), "income": round(income, 2),
        "net": round(income - spent, 2), "budget": float(monthly_budget),
        "projection": round(projection, 2), "per_day": round(per_day, 2),
        "day_now": day_now, "days_in_month": dim,
        "on_track": projection <= float(monthly_budget),
    }


def categories(db, user_id, month):
    rows = month_rows(_rows(db, user_id), month)
    cat = {}
    for r in rows:
        if r.type == "expense":
            cat[r.category] = cat.get(r.category, 0) + float(r.amount)
    total = sum(cat.values()) or 1
    return sorted(
        [{"category": c, "amount": round(a, 2), "share": round(a / total * 100, 1)}
         for c, a in cat.items()],
        key=lambda x: -x["amount"],
    )


def people(db, user_id):
    bal = {}
    for r in _rows(db, user_id):
        if r.type not in IOU_TYPES or not r.person:
            continue
        a = float(r.amount)
        if r.type == "lent":
            bal[r.person] = bal.get(r.person, 0) + a
        elif r.type == "repaid_to_me":
            bal[r.person] = bal.get(r.person, 0) - a
        elif r.type == "borrowed":
            bal[r.person] = bal.get(r.person, 0) - a
        elif r.type == "repaid_by_me":
            bal[r.person] = bal.get(r.person, 0) + a
    out = [{"person": p, "net": round(v, 2)} for p, v in bal.items() if abs(v) >= 1]
    return sorted(out, key=lambda x: -x["net"])


def month_series(db, user_id, n=6):
    rows = _rows(db, user_id)
    by_month = {}
    for r in rows:
        if r.type == "expense":
            k = r.date.strftime("%Y-%m")
            by_month[k] = by_month.get(k, 0) + float(r.amount)
    months = sorted(by_month)[-n:]
    return [{"month": k, "total": round(by_month[k], 2)} for k in months]


def budgets_usage(db, user_id, month):
    rows = month_rows(_rows(db, user_id), month)
    used = {}
    for r in rows:
        if r.type == "expense":
            used[r.category] = used.get(r.category, 0) + float(r.amount)
    caps = db.execute(select(Budget).where(Budget.user_id == user_id)).scalars().all()
    return [{"category": b.category, "cap": float(b.monthly_cap),
             "used": round(used.get(b.category, 0), 2)} for b in caps]


def insights(db, user_id, month, monthly_budget):
    s = summary(db, user_id, month, monthly_budget)
    cats = categories(db, user_id, month)
    usage = {b["category"]: b for b in budgets_usage(db, user_id, month)}
    series = month_series(db, user_id)
    spent = s["spent"]
    out = []

    if cats:
        top = cats[0]
        out.append(f"Biggest category is {top['category']} at ₹{top['amount']:,.0f} "
                   f"({top['share']:.0f}% of spend). Trimming it 20% saves "
                   f"₹{top['amount']*0.2*12:,.0f}/yr.")
    disc = sum(c["amount"] for c in cats if c["category"] in ("food", "luxuries", "clothes"))
    if spent:
        out.append(f"Discretionary load (food + luxuries + clothes) is "
                   f"₹{disc:,.0f} — {disc/spent*100:.0f}% of this month's spend.")
    over = [c for c, b in usage.items() if b["used"] > b["cap"] > 0]
    if over:
        out.append("Over cap: " + ", ".join(over) + ".")
    else:
        out.append("Every category is within its cap. Nice.")
    if len(series) >= 2 and series[-2]["total"] > 0:
        ch = (series[-1]["total"] - series[-2]["total"]) / series[-2]["total"] * 100
        out.append(f"Month over month you're {'up' if ch>=0 else 'down'} "
                   f"{abs(ch):.0f}% (₹{series[-2]['total']:,.0f} → ₹{series[-1]['total']:,.0f}).")
    if s["budget"]:
        if s["on_track"]:
            out.append(f"At this pace you'll finish around ₹{s['projection']:,.0f} — "
                       f"beating budget by ₹{s['budget']-s['projection']:,.0f}.")
        else:
            out.append(f"At this pace you'll finish around ₹{s['projection']:,.0f} — "
                       f"₹{s['projection']-s['budget']:,.0f} over budget.")
    return out
