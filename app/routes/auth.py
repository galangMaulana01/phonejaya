from fastapi import APIRouter, Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from app.config.database import get_db
from app.schemas.auth import LoginRequest, TokenResponse, ProfileUpdateRequest, PasswordChangeRequest
from app.schemas.common import ok
from app.services import auth_service
from app.middlewares.auth import get_current_user
from app.utils.security import verify_password, hash_password

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, body: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    # Access limiter from app state
    limiter = request.app.state.limiter
    # We can't use @limiter.limit decorator directly here due to circular import
    # The limit is enforced by the global default_limits in main.py (100/minute)
    # For specific stricter limits, we'd need to configure on the limiter directly
    return await auth_service.login(db, body.username, body.password)


@router.get("/me")
async def me(request: Request, current_user: dict = Depends(get_current_user), db = Depends(get_db)):
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


@router.patch("/me/profile")
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Update profil sendiri: foto_profil_url dan nama. Username read-only (tidak bisa diganti)."""
    user_id = current_user.get("sub")
    if not user_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=400, detail="User ID tidak valid")

    update_data = {}
    if body.foto_profil_url is not None:
        update_data["foto_profil_url"] = body.foto_profil_url
    if body.name is not None and body.name.strip():
        update_data["name"] = body.name.strip()

    if not update_data:
        return ok({"message": "Tidak ada data yang diupdate"})

    # Convert string ID to ObjectId for MongoDB query
    try:
        obj_id = ObjectId(user_id)
    except Exception:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=400, detail="User ID format tidak valid")

    result = await db.users.update_one(
        {"_id": obj_id},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    # Sync name and foto_profil_url to karyawan collection if exists
    sync_data = {}
    if "name" in update_data:
        sync_data["nama"] = update_data["name"]
    if "foto_profil_url" in update_data:
        sync_data["foto_profil_url"] = update_data["foto_profil_url"]
    
    if sync_data:
        await db.karyawan.update_one(
            {"username": current_user.get("username")},
            {"$set": sync_data}
        )

    # Refresh user data
    updated_user = await db.users.find_one({"_id": obj_id})
    return ok({
        "id": str(updated_user["_id"]),
        "username": updated_user.get("username", ""),
        "name": updated_user.get("name", updated_user.get("username", "")),
        "role": updated_user.get("role", ""),
        "cabang": updated_user.get("cabang", ""),
        "aktif": updated_user.get("aktif", True),
        "foto_profil_url": updated_user.get("foto_profil_url"),
    }, message="Profil berhasil diupdate")


@router.patch("/me/password")
async def change_password(
    body: PasswordChangeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Ganti password sendiri - wajib verifikasi password lama."""
    user_id = current_user.get("sub")
    if not user_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=400, detail="User ID tidak valid")

    # Convert string ID to ObjectId for MongoDB query
    try:
        obj_id = ObjectId(user_id)
    except Exception:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=400, detail="User ID format tidak valid")

    # Get current user with password hash
    user = await db.users.find_one({"_id": obj_id})
    if not user:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    # Verify old password
    stored_hash = user.get("password_hash") or user.get("password", "")
    if not stored_hash or not verify_password(body.password_lama, stored_hash):
        from fastapi import HTTPException, status
        raise HTTPException(status_code=400, detail="Password lama salah")

    # Hash new password
    new_hash = hash_password(body.password_baru)

    # Update password
    await db.users.update_one(
        {"_id": obj_id},
        {"$set": {"password_hash": new_hash}}
    )

    return ok({"message": "Password berhasil diubah. Anda tetap login."})
