from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.security import decode_token

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token tidak valid")
    if payload.get("_expired"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
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


def require_kasir_teknisi_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """Kasir, Teknisi, Kepala Cabang, dan Owner bisa akses."""
    if current_user.get("role") not in ("owner", "kepala_cabang", "kasir", "teknisi"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")
    return current_user


def require_teknisi_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """Teknisi, Kurir, kepala_cabang, dan owner bisa akses."""
    if current_user.get("role") not in ("owner", "kepala_cabang", "teknisi", "kurir"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")
    return current_user


def require_any(current_user: dict = Depends(get_current_user)) -> dict:
    return current_user


def require_kepala_cabang_only(current_user: dict = Depends(get_current_user)) -> dict:
    """Hanya Kepala Cabang yang bisa akses. Owner TIDAK diizinkan."""
    if current_user.get("role") != "kepala_cabang":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya Kepala Cabang yang diizinkan")
    return current_user


def require_influencer(current_user: dict = Depends(get_current_user)) -> dict:
    """Hanya Influencer yang bisa akses."""
    if current_user.get("role") != "influencer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya Influencer yang diizinkan")
    return current_user


def require_influencer_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """Influencer atau Owner bisa akses."""
    if current_user.get("role") not in ("owner", "influencer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")
    return current_user


def require_kurir(current_user: dict = Depends(get_current_user)) -> dict:
    """Hanya Kurir yang bisa akses."""
    if current_user.get("role") != "kurir":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya Kurir yang diizinkan")
    return current_user


def require_kasir(current_user: dict = Depends(get_current_user)) -> dict:
    """Hanya Kasir yang bisa akses."""
    if current_user.get("role") != "kasir":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya Kasir yang diizinkan")
    return current_user


def require_kasir_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """Kasir atau Owner bisa akses."""
    if current_user.get("role") not in ("owner", "kasir"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")
    return current_user
