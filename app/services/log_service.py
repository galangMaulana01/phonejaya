from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase


async def write_log(db: AsyncIOMotorDatabase, user: str, aksi: str, detail: str, cabang: str = "") -> None:
    try:
        await db.log.insert_one({
            "waktu": datetime.now(timezone.utc),
            "user": user, "aksi": aksi,
            "detail": detail, "cabang": cabang,
        })
    except Exception:
        pass
