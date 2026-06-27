"""
Telegram webhook receiver.

In production this is the hot path described in ARCHITECTURE.md §7: validate the
secret header, find the tenant by routing_id (no decryption), dedupe by
update_id, then process. Here we process inline for simplicity; at scale this
handler would enqueue and a worker fleet would do parse/store/reply.
"""

from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from .. import parser, telegram_api
from ..db import SessionLocal
from ..deps import current_user  # noqa: F401 (kept for symmetry)
from ..models import TelegramBot, Txn, User, Budget
from ..security import decrypt_token

router = APIRouter(tags=["telegram"])


def _fmt_inr(n):
    n = int(round(n)); s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]; parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"₹{'-' if n < 0 else ''}{s}"


@router.post("/tg/{routing_id}")
async def telegram_webhook(
    routing_id: str,
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
):
    db = SessionLocal()
    try:
        bot = db.execute(
            select(TelegramBot).where(TelegramBot.routing_id == routing_id)
        ).scalar_one_or_none()
        if bot is None:
            raise HTTPException(404, "unknown bot")

        # auth: the secret Telegram echoes back must match
        if x_telegram_bot_api_secret_token != bot.webhook_secret:
            raise HTTPException(403, "bad secret")

        update = await request.json()
        update_id = update.get("update_id")
        msg = update.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        text = msg.get("text", "")

        # link chat on first contact
        if bot.linked_chat_id is None and chat_id:
            bot.linked_chat_id = chat_id
            db.commit()

        if not text:
            return {"ok": True}

        # /start handshake
        if text.strip().lower().startswith("/start"):
            db.commit()
            _reply(bot, chat_id, "✅ Connected! Just text me what you spent, "
                                 "e.g. “spent 500 on ola”.")
            return {"ok": True}

        # idempotency: skip if we've already stored this update
        if update_id is not None:
            dup = db.execute(
                select(Txn).where(Txn.user_id == bot.user_id,
                                  Txn.tg_update_id == update_id)
            ).scalar_one_or_none()
            if dup:
                return {"ok": True}

        p = parser.parse(text)
        if p["amount"] is None:
            _reply(bot, chat_id, "Couldn't find an amount — try “spent 500 on ola”.")
            return {"ok": True}

        db.add(Txn(user_id=bot.user_id, category=p["category"], amount=p["amount"],
                   note=p["note"], type=p["type"], person=p["person"],
                   source="telegram", tg_update_id=update_id))
        db.commit()

        _reply(bot, chat_id, _confirm(db, bot.user_id, p))
        return {"ok": True}
    finally:
        db.close()


def _confirm(db, user_id, p):
    if p["type"] in ("lent", "borrowed", "repaid_to_me", "repaid_by_me"):
        who = p.get("person") or "someone"
        return f"✅ {p['type'].replace('_', ' ')} {_fmt_inr(p['amount'])} · {who}"
    user = db.get(User, user_id)
    return f"✅ {p['category']} {_fmt_inr(p['amount'])} — {p['note']}"


def _reply(bot, chat_id, text):
    if not chat_id:
        return
    try:
        token = decrypt_token(bot.token_ciphertext)
        telegram_api.send_message(token, chat_id, text)
    except Exception:
        pass  # offline/dev: storing still succeeded
