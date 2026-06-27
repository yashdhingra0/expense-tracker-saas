"""Connect / list / disconnect Telegram bots (bring-your-own-token)."""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import telegram_api
from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import User, TelegramBot
from ..schemas import BotConnectIn
from ..security import encrypt_token, decrypt_token

router = APIRouter(prefix="/bots", tags=["bots"])

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")


def _bot_out(b: TelegramBot):
    return {"id": b.id, "username": b.bot_username, "status": b.status,
            "routing_id": b.routing_id, "linked": b.linked_chat_id is not None}


@router.post("/connect")
def connect(body: BotConnectIn, db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    token = body.token.strip()
    if not TOKEN_RE.match(token):
        raise HTTPException(422, "That doesn't look like a bot token. It should "
                                 "look like 123456789:AA... (copy the whole thing "
                                 "from BotFather, including the part before the colon).")

    # 1) validate with Telegram
    ok, info = telegram_api.get_me(token)
    if not ok and not settings.dev_allow_unverified_tokens:
        raise HTTPException(400, "Telegram rejected that token. Double-check it "
                                 "or generate a fresh one with /token in BotFather.")
    result = info.get("result", {}) if ok else {}

    # 2) enforce 1 key/bot limit per user, then store new bot
    existing_bots = db.execute(
        select(TelegramBot).where(TelegramBot.user_id == user.id)
    ).scalars().all()
    for existing in existing_bots:
        try:
            telegram_api.delete_webhook(decrypt_token(existing.token_ciphertext))
        except Exception:
            pass
        db.delete(existing)
    db.flush()

    bot = TelegramBot(
        user_id=user.id,
        bot_telegram_id=result.get("id"),
        bot_username=result.get("username") or "pending",
        token_ciphertext=encrypt_token(token),
        status="active" if ok else "pending",
    )
    db.add(bot)
    db.flush()

    # 3) register webhook
    webhook_url = f"{settings.public_base_url}/tg/{bot.routing_id}"
    ok_webhook, webhook_data = telegram_api.set_webhook(token, webhook_url, bot.webhook_secret)
    
    # Log details to stdout (visible in Vercel Logs)
    print(f"[BOT CONNECT] public_base_url: {settings.public_base_url}")
    print(f"[BOT CONNECT] webhook_url: {webhook_url}")
    print(f"[BOT CONNECT] set_webhook result: ok={ok_webhook}, data={webhook_data}")

    if not ok_webhook and not settings.dev_allow_unverified_tokens:
        error_msg = webhook_data.get("description", "Unknown Telegram error")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to register webhook with Telegram: {error_msg}. Verify PUBLIC_BASE_URL settings."
        )

    db.commit()
    return {"ok": True, "bot": _bot_out(bot),
            "verified": ok,
            "next": "Open your bot in Telegram and send /start to finish linking."}


@router.get("")
def list_bots(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(TelegramBot).where(TelegramBot.user_id == user.id)).scalars().all()
    return [_bot_out(b) for b in rows]


@router.post("/{bot_id}/disconnect")
def disconnect(bot_id: str, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    bot = db.get(TelegramBot, bot_id)
    if bot is None or bot.user_id != user.id:
        raise HTTPException(404, "Not found")
    try:
        telegram_api.delete_webhook(decrypt_token(bot.token_ciphertext))
    except Exception:
        pass
    db.delete(bot)
    db.commit()
    return {"ok": True}
