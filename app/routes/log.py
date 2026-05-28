from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.common import ok
from app.utils.formatters import fmt_waktu
from app.middlewares.auth import require_owner

router = APIRouter(prefix="/log", tags=["Log"])


@router.get("")
async def list_log(
    cabang: Optional[str] = Query(None),
    limit:  int = Query(100, ge=1, le=500),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    _user:  dict = Depends(require_owner),
):
    query = {}
    if cabang:
        query["cabang"] = cabang
    cursor = db.log.find(query).sort("waktu", -1).limit(limit)
    docs   = await cursor.to_list(length=limit)
    data = [{
        "id":     str(d["_id"]),
        "waktu":  fmt_waktu(d["waktu"]),
        "user":   d["user"],
        "aksi":   d["aksi"],
        "detail": d["detail"],
        "cabang": d.get("cabang", ""),
    } for d in docs]
    return ok(data)
