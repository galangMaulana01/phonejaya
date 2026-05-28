from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException, status
from app.utils.security import verify_password, create_access_token
from app.schemas.auth import TokenResponse, UserPublic


async def login(db: AsyncIOMotorDatabase, username: str, password: str) -> TokenResponse:
    user = await db.users.find_one({"username": username})

    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah",
        )

    if not user.get("aktif", True):
        raise HTTPException(status_code=403, detail="Akun tidak aktif")

    token = create_access_token({
        "sub": str(user["_id"]),
        "role": user["role"],
        "cabang": user["cabang"],
    })

    return TokenResponse(
        access_token=token,
        user=UserPublic(
            id=str(user["_id"]),
            username=user["username"],
            name=user["name"],
            role=user["role"],
            cabang=user["cabang"],
        ),
    )
