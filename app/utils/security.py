"""
Security utils — pakai bcrypt langsung (bukan passlib)
agar kompatibel dengan Vercel serverless environment.
"""
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError, ExpiredSignatureError
from app.config.settings import settings


# ── Password ──────────────────────────────────────────────
def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────
def create_access_token(payload: dict, expires_delta: Optional[timedelta] = None) -> str:
    data = payload.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    data["exp"] = expire
    return jwt.encode(data, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Return payload dict, atau None jika token invalid/expired."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except ExpiredSignatureError:
        # Return payload dengan flag expired agar frontend bisa unterscheiden
        try:
            # Decode tanpa verify expiry untuk ambil payload
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM], options={"verify_exp": False})
            payload["_expired"] = True
            return payload
        except JWTError:
            return None
    except JWTError:
        return None
