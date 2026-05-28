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
async def me(current_user: dict = Depends(get_current_user)):
    return ok({
        "id":       str(current_user["_id"]),
        "username": current_user["username"],
        "name":     current_user["name"],
        "role":     current_user["role"],
        "cabang":   current_user["cabang"],
    })
