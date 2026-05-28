from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from app.utils.security import decode_token
from app.config.database import get_db
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token tidak valid atau sudah expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user or not user.get("aktif", True):
        raise credentials_exc
    return user


def require_owner(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Akses ditolak. Hanya owner.")
    return current_user


def require_kasir_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") not in ("owner", "kasir"):
        raise HTTPException(status_code=403, detail="Akses ditolak.")
    return current_user


def require_teknisi_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") not in ("owner", "teknisi"):
        raise HTTPException(status_code=403, detail="Akses ditolak.")
    return current_user


def require_any(current_user: dict = Depends(get_current_user)) -> dict:
    return current_user
