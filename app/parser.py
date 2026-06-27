"""
parser.py — natural-language message -> {amount, category, note, type, person}.

This is the same engine proven in the single-user prototype, reused verbatim
as the platform's parsing library. type is one of:
  expense | income | lent | borrowed | repaid_to_me | repaid_by_me
IOU types carry a `person`.
"""

import re

CATEGORY_KEYWORDS = {
    "travel": ["ola", "uber", "rapido", "metro", "auto", "rickshaw", "cab",
               "taxi", "bus", "train", "irctc", "flight", "petrol", "diesel",
               "fuel", "fastag", "toll", "parking", "redbus"],
    "food": ["swiggy", "zomato", "chai", "coffee", "starbucks", "dinner",
             "lunch", "breakfast", "restaurant", "cafe", "dominos", "pizza",
             "burger", "kfc", "biryani", "snack", "food", "tea", "dosa"],
    "groceries": ["blinkit", "zepto", "bigbasket", "instamart", "dmart",
                  "grocery", "groceries", "vegetables", "milk", "supermarket",
                  "kirana", "fruits"],
    "clothes": ["myntra", "ajio", "zara", "shirt", "tshirt", "jeans", "shoes",
                "sneakers", "nike", "adidas", "clothes", "dress", "kurta",
                "jacket", "footwear", "apparel"],
    "rent": ["rent", "landlord", "lease", "maintenance", "society", "deposit",
             "hostel"],
    "bills": ["electricity", "broadband", "wifi", "internet", "airtel", "jio",
              "vodafone", "recharge", "dth", "bill", "mobile", "postpaid",
              "prepaid", "emi"],
    "luxuries": ["netflix", "spotify", "prime", "hotstar", "gym", "movie",
                 "cinema", "pvr", "inox", "bookmyshow", "game", "party",
                 "bar", "subscription", "amazon", "flipkart", "gadget", "gift"],
    "investments": ["sip", "etf", "stocks", "stock", "mutual fund", "zerodha",
                    "groww", "upstox", "nps", "ppf", "gold", "crypto",
                    "bitcoin", "invest", "investment", "shares"],
    "health": ["medicine", "pharmacy", "apollo", "pharmeasy", "1mg", "doctor",
               "hospital", "clinic", "checkup", "dentist", "medical", "health"],
    "education": ["course", "udemy", "coursera", "book", "books", "tuition",
                  "fees", "fee", "exam", "college", "class", "kindle",
                  "stationery", "education"],
}

INCOME_KEYWORDS = ["salary", "income", "refund", "refunded", "cashback",
                   "received", "credited", "credit", "got paid", "reimburse",
                   "reimbursed", "bonus", "dividend", "payout"]

LENT_KEYWORDS = ["lent", "lend", "loaned"]
BORROW_KEYWORDS = ["borrowed", "borrow"]
SETTLE_KEYWORDS = ["paid back", "pay back", "payback", "returned", "repaid",
                   "got back", "received back", "gave back", "settled up"]

FILLER_WORDS = {
    "spent", "spend", "paid", "pay", "for", "on", "at", "to", "the", "a", "an",
    "got", "received", "credited", "rs", "rs.", "inr", "rupees", "rupee", "of",
    "in", "my", "some", "this", "that", "and", "with", "today", "yesterday",
    "via", "by", "bought", "buy", "purchase", "purchased", "from", "back",
    "lent", "lend", "borrowed", "borrow", "returned", "repaid", "gave", "give",
}
NOT_NAMES = {"me", "him", "her", "them", "office", "work", "home", "bank",
             "shop", "store", "the", "a", "an", "it"}

_AMOUNT_RE = re.compile(
    r"(?:rs\.?\s*|₹\s*|inr\s*)?(\d[\d,]*(?:\.\d+)?)\s*"
    r"(k|l|lac|lakh|lakhs|cr|crore|crores)?(?:\s*(?:rs\.?|₹|rupees?))?",
    re.IGNORECASE,
)
_MULT = {"k": 1_000, "l": 1e5, "lac": 1e5, "lakh": 1e5, "lakhs": 1e5,
         "cr": 1e7, "crore": 1e7, "crores": 1e7}


def extract_amount(text):
    cands = []
    for m in _AMOUNT_RE.finditer(text):
        num, suf = m.group(1), m.group(2)
        if num in (".", ""):
            continue
        try:
            val = float(num.replace(",", "")) * (_MULT[suf.lower()] if suf else 1)
        except (ValueError, KeyError):
            continue
        if val <= 0:
            continue
        marker = bool(suf) or any(s in m.group(0).lower()
                                  for s in ("rs", "₹", "inr", "rupee"))
        cands.append((val, marker, m.span()))
    if not cands:
        return None, None
    pool = [c for c in cands if c[1]] or cands
    best = max(pool, key=lambda c: c[0])
    return best[0], best[2]


def _clean_name(tok):
    if not tok:
        return None
    name = re.sub(r"[^A-Za-z]", "", tok)
    return name.capitalize() if name and name.lower() not in NOT_NAMES else None


def _person_after(word, text):
    m = re.search(rf"\b{word}\s+([A-Za-z]+)", text, re.IGNORECASE)
    return _clean_name(m.group(1)) if m else None


def detect_iou(text):
    low = text.lower()
    if any(k in low for k in BORROW_KEYWORDS):
        return "borrowed", _person_after("from", text)
    if any(k in low for k in LENT_KEYWORDS):
        return "lent", _person_after("to", text)
    if any(k in low for k in SETTLE_KEYWORDS):
        to_p = _person_after("to", text)
        from_p = _person_after("from", text)
        i_paid = re.search(r"\bi\s+(?:paid|returned|repaid|gave)\b", low)
        if to_p or i_paid:
            return "repaid_by_me", to_p
        if from_p:
            return "repaid_to_me", from_p
        m = re.search(r"^\s*([A-Za-z]+)\b", text)
        return "repaid_to_me", (_clean_name(m.group(1)) if m else None)
    if re.search(r"\bgave\b", low) and re.search(r"\bto\b", low) \
            and not any(k in low for k in INCOME_KEYWORDS):
        return "lent", _person_after("to", text)
    return None


def guess_category(text):
    low = text.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in low for kw in kws):
            return cat
    return "other"


def is_income(text):
    return any(kw in text.lower() for kw in INCOME_KEYWORDS)


def build_note(text, span, extra_drop=None):
    if span:
        text = text[:span[0]] + " " + text[span[1]:]
    text = text.replace("₹", " ")
    drop = set(FILLER_WORDS) | ({w.lower() for w in extra_drop} if extra_drop else set())
    out = []
    for tok in re.split(r"\s+", text.strip()):
        bare = tok.strip(".,!?:;").lower()
        if not bare or bare in drop or re.fullmatch(r"[\d,]+(?:\.\d+)?", bare):
            continue
        out.append(tok.strip(".,!?:;"))
    return " ".join(out).strip()


def parse(text):
    text = (text or "").strip()
    amount, span = extract_amount(text)
    iou = detect_iou(text)
    if iou:
        t, person = iou
        return {"amount": amount, "category": "iou",
                "note": build_note(text, span, [person] if person else None) or (person or "iou"),
                "type": t, "person": person}
    if is_income(text):
        return {"amount": amount, "category": "income",
                "note": build_note(text, span) or "income",
                "type": "income", "person": None}
    return {"amount": amount, "category": guess_category(text),
            "note": build_note(text, span) or "misc",
            "type": "expense", "person": None}
