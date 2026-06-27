"""Thin Telegram Bot API helpers. Network failures are returned, not raised,
so the app behaves sanely offline (dev) and in production."""

import httpx

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, payload=None, timeout=10):
    try:
        r = httpx.post(API.format(token=token, method=method),
                       json=payload or {}, timeout=timeout)
        data = r.json()
        return data.get("ok", False), data
    except Exception as e:  # network/parse errors -> graceful
        return False, {"error": str(e)}


def get_me(token: str):
    return _call(token, "getMe")


def set_webhook(token: str, url: str, secret: str):
    return _call(token, "setWebhook", {
        "url": url,
        "secret_token": secret,
        "allowed_updates": ["message"],
    })


def delete_webhook(token: str):
    return _call(token, "deleteWebhook")


def send_message(token: str, chat_id: int, text: str):
    return _call(token, "sendMessage", {"chat_id": chat_id, "text": text})
