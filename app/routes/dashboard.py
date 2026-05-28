from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.common import ok
from app.services import dashboard_service
from app.middlewares.auth import require_owner

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def dashboard_stats(
    cabang: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    _user:  dict = Depends(require_owner),
):
    stats = await dashboard_service.get_stats(db, cabang=cabang)
    return ok(stats)
