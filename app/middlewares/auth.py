from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.security import decode_token

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token tidak valid")
    if not payload.get("aktif", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun nonaktif")
    return payload


def require_owner(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya Owner yang diizinkan")
    return current_user


def require_kepala_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") not in ("owner", "kepala_cabang"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")
    return current_user


def require_kasir_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") not in ("owner", "kasir", "kepala_cabang"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")
    return current_user


def require_teknisi_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """Teknisi, kepala_cabang, dan owner bisa akses."""
    if current_user.get("role") not in ("owner", "kepala_cabang", "teknisi"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")
    return current_user


def require_any(current_user: dict = Depends(get_current_user)) -> dict:
    return current_user
