from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.common import ok
from app.services import auth_service
from app.middlewares.auth import get_current_user

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await auth_service.login(db, body.username, body.password)


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user), db = Depends(get_db)):
    # JWT payload pakai "sub" untuk id, bukan "_id"
    # Lookup foto_profil_url from karyawan collection
    foto_profil_url = None
    karyawan = await db.karyawan.find_one({"username": current_user.get("username", "")})
    if karyawan:
        foto_profil_url = karyawan.get("foto_profil_url")
    return ok({
        "id":       current_user.get("sub", ""),
        "username": current_user.get("username", ""),
        "name":     current_user.get("name", current_user.get("username", "")),
        "role":     current_user.get("role", ""),
        "cabang":   current_user.get("cabang", ""),
        "aktif":    current_user.get("aktif", True),
        "foto_profil_url": foto_profil_url,
    })
