from motor.motor_asyncio import AsyncIOMotorDatabase

_KATEGORI_MAP = {
    "IP": "iPhone", "AI": "Android", "TB": "Tablet",
    "AC": "Accessories", "SP": "Sparepart"
}
_KONDISI_MAP = {
    "BN": "Normal", "MN": "Minus", "EX": "Ex Inter", "RJ": "Reject"
}


async def _next_seq(db: AsyncIOMotorDatabase, key: str) -> int:
    result = await db.counters.find_one_and_update(
        {"_id": key},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return result["seq"]


async def next_unit_id(db, kat: str, kondisi: str, cabang: str = "JYP") -> str:
    # Counter per (cabang, kategori) agar tidak tabrakan antar cabang
    seq = await _next_seq(db, f"{cabang}-{kat}")
    return f"{cabang}-{kat}-{kondisi}-{str(seq).zfill(3)}"


async def next_trx_id(db, cabang: str = "") -> str:
    key = f"TRX-{cabang}" if cabang else "TRX"
    seq = await _next_seq(db, key)
    prefix = f"{cabang}-TRX" if cabang else "TRX"
    return f"{prefix}-{str(seq).zfill(3)}"


async def next_service_id(db) -> str:
    seq = await _next_seq(db, "SVC")
    return f"SVC-{str(seq).zfill(3)}"


def resolve_kategori(kat_kode: str) -> str:
    return _KATEGORI_MAP.get(kat_kode, kat_kode)


def resolve_kondisi(kondisi_kode: str) -> str:
    return _KONDISI_MAP.get(kondisi_kode, kondisi_kode)


async def next_video_id(db: AsyncIOMotorDatabase, cabang: str) -> str:
    """
    Generate video ID: {CABANG}-VID-{SEQ}
    Counter per cabang.
    """
    seq = await _next_seq(db, f"{cabang}-VID")
    return f"{cabang}-VID-{str(seq).zfill(3)}"


def _parse_kode(unit_id: str) -> tuple[str, str]:
    """
    Ekstrak kat_kode dan kondisi_kode dari unit_id.
    Format: {CABANG}-{KAT}-{KONDISI}-{SEQ}
    Contoh: JYP-IP-BN-001 → ('IP', 'BN')
    """
    parts = unit_id.split("-")
    if len(parts) < 4:
        raise ValueError(f"Format unit_id tidak valid: {unit_id}")
    # parts[0] = cabang, parts[1] = kat, parts[2] = kondisi, parts[-1] = seq
    kat_kode = parts[1]
    kondisi_kode = parts[2]
    return kat_kode, kondisi_kode