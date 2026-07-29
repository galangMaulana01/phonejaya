from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.unit_modal_history import UnitModalHistoryResponse
from app.schemas.common import ok
from app.services import unit_modal_history
from app.middlewares.auth import require_kepala_or_owner

router = APIRouter(prefix="/units", tags=["Unit Modal History"])


@router.get("/{unit_id}/modal-history")
async def get_modal_history(
    unit_id: str,
    limit: int = Query(50, ge=1, le=100),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    """Get modal history for a unit (Owner/Kepala Cabang only)"""
    # Validate cabang ownership
    if user.get("role") != "owner":
        unit = await db.units.find_one({"unit_id": unit_id})
        if not unit or unit.get("cabang") != user.get("cabang"):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Unit bukan milik cabang Anda")

    history = await unit_modal_history.list_modal_history(
        db, unit_id=unit_id, limit=limit, date_from=date_from, date_to=date_to
    )
    return ok([h.model_dump() for h in history])