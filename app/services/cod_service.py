from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.cod import (
    CODRequestCreate, CODStatusUpdate, CODRequestResponse,
    CODRequestList, CODRequestDetail, KurirListItem
)
from app.utils.id_generator import next_cod_id
from app.services.log_service import write_log


# Status flow definitions
COD_BELI_FLOW = {
    "menunggu_kurir": ["diterima", "ditolak"],
    "diterima": ["kurir_menuju_lokasi"],
    "kurir_menuju_lokasi": ["sudah_bertemu_penjual", "ditolak"],
    "sudah_bertemu_penjual": ["input_stok", "ditolak"],
    "input_stok": ["selesai"],
    "selesai": [],
    "ditolak": [],
}

COD_JUAL_FLOW = {
    "menunggu_kurir": ["diterima", "ditolak"],
    "diterima": ["barang_akan_dijemput"],
    "barang_akan_dijemput": ["barang_sudah_diambil"],
    "barang_sudah_diambil": ["kurir_sedang_transaksi"],
    "kurir_sedang_transaksi": ["transaksi_berhasil", "gagal"],
    "transaksi_berhasil": [],
    "gagal": [],
    "ditolak": [],
}

ALL_FLOWS = {
    "beli": COD_BELI_FLOW,
    "jual": COD_JUAL_FLOW,
}

INITIAL_STATUS = {
    "beli": "menunggu_kurir",
    "jual": "menunggu_kurir",
}


async def create_cod_request(
    db: AsyncIOMotorDatabase,
    payload: CODRequestCreate,
    kasir_id: str,
    kasir_name: str,
    cabang: str,
    actor: str
) -> CODRequestResponse:
    """Kasir buat request COD (Beli atau Jual)."""
    
    # Validasi kurir ada di cabang yang sama
    kurir = await db.users.find_one({
        "username": payload.kurir_id,
        "role": "Kurir",
        "cabang": cabang,
        "aktif": True
    })
    if not kurir:
        raise HTTPException(status_code=404, detail="Kurir tidak ditemukan atau tidak aktif di cabang Anda")
    
    cod_id = await next_cod_id(db, cabang)
    now = datetime.now(timezone.utc)
    
    initial_status = INITIAL_STATUS[payload.type]
    
    status_history = [{
        "status": initial_status,
        "by": actor,
        "at": now,
        "note": "Request dibuat"
    }]
    
    doc = {
        "cod_id": cod_id,
        "type": payload.type,
        "status": initial_status,
        "screenshot_url": payload.screenshot_url,
        "product_link": payload.product_link,
        "product_name": payload.product_name,
        "offer_price": payload.offer_price,
        "note": payload.note,
        "location": payload.location,
        "wa_number": payload.wa_number,
        "transaksi_id": payload.transaksi_id,
        "kasir_id": kasir_id,
        "kasir_name": kasir_name,
        "kurir_id": payload.kurir_id,
        "kurir_name": kurir.get("name", payload.kurir_id),
        "cabang": cabang,
        "status_history": status_history,
        "created_at": now,
        "updated_at": now,
    }
    
    result = await db.cod_requests.insert_one(doc)
    doc["_id"] = result.inserted_id
    
    await write_log(
        db, actor, "Buat COD Request",
        f"{cod_id} → {payload.type.upper()} {payload.product_name or ''} ({payload.offer_price or 0})",
        cabang
    )
    
    return _format_cod_response(doc)


async def update_cod_status(
    db: AsyncIOMotorDatabase,
    cod_id: str,
    new_status: str,
    actor: str,
    actor_name: str,
    note: Optional[str] = None
) -> CODRequestResponse:
    """Update status COD (dipakai Kurir accept/reject/update status)."""
    
    doc = await db.cod_requests.find_one({"cod_id": cod_id})
    if not doc:
        raise HTTPException(status_code=404, detail="COD Request tidak ditemukan")
    
    # Validasi hak akses - hanya kurir yang ditugaskan
    if doc.get("kurir_id") != actor:
        raise HTTPException(status_code=403, detail="Bukan kurir yang ditugaskan")
    
    # Validasi transisi status
    current = doc["status"]
    flow = ALL_FLOWS[doc["type"]]
    
    if new_status not in flow.get(current, []):
        raise HTTPException(
            status_code=400, 
            detail=f"Transisi status dari '{current}' ke '{new_status}' tidak diizinkan untuk tipe {doc['type']}"
        )
    
    now = datetime.now(timezone.utc)
    status_history = doc.get("status_history", [])
    status_history.append({
        "status": new_status,
        "by": actor,
        "by_name": actor_name,
        "at": now,
        "note": note
    })
    
    await db.cod_requests.update_one(
        {"cod_id": cod_id},
        {"$set": {
            "status": new_status,
            "status_history": status_history,
            "updated_at": now
        }}
    )
    
    doc = await db.cod_requests.find_one({"cod_id": cod_id})
    
    await write_log(
        db, actor, "Update COD Status",
        f"{cod_id} → {current} → {new_status}" + (f" ({note})" if note else ""),
        doc["cabang"]
    )
    
    return _format_cod_response(doc)


async def list_cod_requests(
    db: AsyncIOMotorDatabase,
    cabang: str,
    kurir_id: str,
    kurir_name: str,
    status: Optional[str] = None,
    type_filter: Optional[str] = None
) -> List[CODRequestList]:
    """Dashboard Kurir: list COD requests yang assigned ke kurir ini."""
    
    query = {"cabang": cabang, "kurir_id": kurir_id}
    if status:
        query["status"] = status
    if type_filter:
        query["type"] = type_filter
    
    cursor = db.cod_requests.find(query).sort("created_at", -1).limit(100)
    docs = await cursor.to_list(length=100)
    
    return [_format_dashboard_item(d) for d in docs]


async def list_cod_requests_all(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str],
    status: Optional[str] = None,
    type_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100
) -> List[CODRequestList]:
    """List COD untuk Kasir/KC/Owner."""
    
    query = {}
    if cabang:
        query["cabang"] = cabang
    if status:
        query["status"] = status
    if type_filter:
        query["type"] = type_filter
    if date_from or date_to:
        from datetime import datetime, timezone
        wf = {}
        if date_from:
            wf["$gte"] = datetime.fromisoformat(date_from.replace("Z", "")).replace(tzinfo=timezone.utc)
        if date_to:
            wf["$lte"] = datetime.fromisoformat(date_to.replace("Z", "")).replace(tzinfo=timezone.utc)
        query["created_at"] = wf
    
    cursor = db.cod_requests.find(query).sort("created_at", -1).limit(limit)
    docs = await cursor.to_list(length=limit)
    
    return [_format_dashboard_item(d) for d in docs]


async def get_cod_detail(
    db: AsyncIOMotorDatabase,
    cod_id: str
) -> CODRequestDetail:
    """Get detail COD request."""
    
    doc = await db.cod_requests.find_one({"cod_id": cod_id})
    if not doc:
        raise HTTPException(status_code=404, detail="COD Request tidak ditemukan")
    
    return CODRequestDetail(
        cod_id=doc["cod_id"],
        type=doc["type"],
        status=doc["status"],
        created_at=doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else str(doc["created_at"]),
        updated_at=doc["updated_at"].isoformat() if isinstance(doc["updated_at"], datetime) else str(doc["updated_at"]),
        location=doc["location"],
        wa_number=doc["wa_number"],
        screenshot_url=doc["screenshot_url"],
        note=doc.get("note"),
        product_name=doc.get("product_name"),
        offer_price=doc.get("offer_price"),
        product_link=doc.get("product_link"),
        transaksi_id=doc.get("transaksi_id"),
        kasir_id=doc["kasir_id"],
        kasir_name=doc["kasir_name"],
        kurir_id=doc.get("kurir_id"),
        kurir_name=doc.get("kurir_name"),
        status_history=doc.get("status_history", []),
    )


async def get_kurir_list(db: AsyncIOMotorDatabase, cabang: str) -> List[KurirListItem]:
    """List kurir aktif di cabang."""
    cursor = db.users.find({"role": "Kurir", "cabang": cabang, "aktif": True})
    kurirs = await cursor.to_list(length=None)
    return [KurirListItem(kurir_id=k["username"], kurir_name=k.get("name", k["username"]), cabang=k["cabang"]) for k in kurirs]


# Helper functions

def _format_cod_response(doc: dict) -> CODRequestResponse:
    return CODRequestResponse(
        cod_id=doc["cod_id"],
        type=doc["type"],
        status=doc["status"],
        created_at=doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else str(doc["created_at"]),
    )


def _format_dashboard_item(doc: dict) -> CODRequestList:
    return CODRequestList(
        cod_id=doc["cod_id"],
        type=doc["type"],
        status=doc["status"],
        created_at=doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else str(doc["created_at"]),
        location=doc["location"],
        wa_number=doc["wa_number"],
        screenshot_url=doc["screenshot_url"],
        product_name=doc.get("product_name"),
        offer_price=doc.get("offer_price"),
        kasir_name=doc["kasir_name"],
        kurir_name=doc.get("kurir_name"),
        kurir_id=doc.get("kurir_id"),
    )