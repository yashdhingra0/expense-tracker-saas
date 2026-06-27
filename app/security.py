"""
Passwords, signed sessions, and Telegram-token encryption.

In production the token encryption here would be backed by a managed KMS
(AWS KMS / GCP KMS / Vault). For local dev we use Fernet (AES-128-CBC + HMAC)
with a key from the environment — same contract (encrypt/decrypt bytes), no
cloud dependency. See ARCHITECTURE.md §6.
"""

from typing import Optional
import base64
import hashlib
import bcrypt

from cryptography.fernet import Fernet
from itsdangerous import URLSafeSerializer, BadSignature

from .config import settings

# --- passwords --------------------------------------------------------------
def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


# --- signed session cookie --------------------------------------------------
_serializer = URLSafeSerializer(settings.secret_key, salt="session")


def make_session(user_id: str) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session(cookie: Optional[str]) -> Optional[str]:
    if not cookie:
        return None
    try:
        return _serializer.loads(cookie).get("uid")
    except BadSignature:
        return None


# --- token encryption (KMS stand-in) ----------------------------------------
def _fernet() -> Fernet:
    key = settings.token_enc_key
    if not key:
        # Dev fallback: derive a stable key from SECRET_KEY so restarts can
        # still decrypt. NEVER rely on this in production — set TOKEN_ENC_KEY.
        digest = hashlib.sha256(settings.secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_token(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()
