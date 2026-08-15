from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
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
    "input_stok": ["menunggu_approval_kasir"],
    "menunggu_approval_kasir": ["processing_approval", "ditolak"],  # approve → claim, reject → ditolak
    "processing_approval": ["selesai", "menunggu_approval_kasir"],  # finalize or revert on failure
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

COD_DELIVERY_FLOW = {
    "menunggu_kurir": ["diterima", "ditolak"],
    "diterima": ["kurir_menuju_toko"],
    "kurir_menuju_toko": ["barang_sudah_diambil"],
    "barang_sudah_diambil": ["sedang_diantar"],
    "sedang_diantar": ["terkirim", "gagal"],
    "terkirim": [],
    "gagal": [],
    "ditolak": [],
}

ALL_FLOWS = {
    "beli": COD_BELI_FLOW,
    "jual": COD_JUAL_FLOW,
    "delivery": COD_DELIVERY_FLOW,
}

INITIAL_STATUS = {
    "beli": "menunggu_kurir",
    "jual": "menunggu_kurir",
    "delivery": "menunggu_kurir",
}


async def create_cod_request(
    db: AsyncIOMotorDatabase,
    payload: CODRequestCreate,
    kasir_id: str,
    kasir_name: str,
    cabang: str,
    actor: str,
    role: str = "kasir"
) -> CODRequestResponse:
    """Kasir buat request COD (Beli, Jual, atau Delivery)."""
    
    from app.utils.upload_urls import ensure_uploaded_asset
    ensure_uploaded_asset(payload.screenshot_url, "screenshot_url")
    kurir = None
    kurir_name_val = None
    
    # Broadcast: beli & delivery = no kurir assigned, will be claimed by kurir.
    # Jual only = manual assign.
    if payload.type == "jual":
        # Manual assign: validate kurir exists in same cabang
        if not payload.kurir_id:
            raise HTTPException(status_code=422, detail="kurir_id wajib untuk type jual")
        kurir = await db.users.find_one({
            "username": payload.kurir_id,
            "role": "Kurir",
            "cabang": cabang,
            "aktif": True
        })
        if not kurir:
            raise HTTPException(status_code=404, detail="Kurir tidak ditemukan atau tidak aktif di cabang Anda")
        kurir_name_val = kurir.get("name", payload.kurir_id)

    # COD Jual bukan jalur untuk membuat transaksi baru. Wajib ada transaksi
    # unit yang sudah diklaim kasir, pada cabang yang sama, sehingga hubungan
    # cod → transaksi → unit bersifat tunggal dan dapat diaudit.
    if payload.type == "jual":
        if not payload.trx_id or not payload.unit_id:
            raise HTTPException(status_code=422, detail="trx_id dan unit_id wajib untuk COD Jual")
        trx = await db.transaksi.find_one({"trx_id": payload.trx_id, "cabang": cabang})
        if not trx:
            raise HTTPException(status_code=404, detail="Transaksi COD Jual tidak ditemukan di cabang Anda")
        if trx.get("unit_id") != payload.unit_id:
            raise HTTPException(status_code=422, detail="Unit COD Jual harus sama dengan unit pada transaksi")
        unit = await db.units.find_one({"unit_id": payload.unit_id, "cabang": cabang})
        if not unit or unit.get("status") != "Sold":
            raise HTTPException(status_code=409, detail="Unit COD Jual harus sudah berstatus Sold pada transaksi yang sama")
        used = await db.cod_requests.find_one({
            "type": "jual", "trx_id": payload.trx_id,
            "status": {"$nin": ["ditolak", "gagal", "transaksi_berhasil"]},
        })
        if used:
            raise HTTPException(status_code=409, detail=f"Transaksi sudah terikat COD Jual aktif ({used['cod_id']})")

    cod_id = await next_cod_id(db, cabang)
    now = datetime.now(timezone.utc)
    
    initial_status = INITIAL_STATUS[payload.type]
    
    status_history = [{
        "status": initial_status,
        "by": actor,
        "at": now,
        "note": "Request dibuat"
    }]
    
    # Delivery-specific fields
    delivery_address = ""
    wa_customer = ""
    items = []
    trx_id_val = None
    
    if payload.type == "delivery":
        # Validasi trx_id wajib
        if not payload.trx_id:
            raise HTTPException(status_code=422, detail="trx_id wajib untuk type delivery")
        
        # Validasi transaksi exists
        trx = await db.transaksi.find_one({"trx_id": payload.trx_id})
        if not trx:
            raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
        
        # Validasi ownership: cabang harus sama
        if trx.get("cabang") != cabang:
            raise HTTPException(status_code=403, detail="Transaksi bukan milik cabang Anda")
        
        # Validasi ownership: kasir harus pemilik transaksi (owner/KC bisa akses semua)
        if role not in ("owner", "kepala_cabang"):
            if trx.get("kasir") != kasir_name:
                raise HTTPException(status_code=403, detail="Anda hanya bisa mengirim transaksi milik Anda sendiri")
        
        # Cek belum ada COD delivery aktif untuk transaksi ini
        existing = await db.cod_requests.find_one({
            "trx_id": payload.trx_id, "type": "delivery",
            "status": {"$nin": ["ditolak", "gagal", "terkirim"]}
        })
        if existing:
            raise HTTPException(status_code=409, detail=f"COD delivery sudah ada ({existing['cod_id']}) untuk transaksi ini")
        
        # Build items dari transaksi
        if trx.get("unit_id"):
            items.append({"type": "unit", "unit_id": trx["unit_id"], "label": trx.get("unit_label", "")})
        for sp in (trx.get("sp_items") or []):
            items.append({"type": "sparepart", "sp_id": sp.get("sp_id", ""), "nama": sp.get("nama", ""), "jumlah": sp.get("jumlah", 1)})
        
        delivery_address = payload.delivery_address or ""
        wa_customer = payload.wa_customer or trx.get("customer_kontak", "")
        trx_id_val = payload.trx_id
        
        # Auto-fill product_name dan offer_price dari transaksi
        product_name = payload.product_name or trx.get("unit_label", "") or f"{len(items)} item"
        offer_price = payload.offer_price or trx.get("harga_jual", 0)
    else:
        trx_id_val = payload.trx_id
        product_name = payload.product_name
        offer_price = payload.offer_price
        if payload.type == "jual":
            product_name = product_name or f"COD Jual {payload.unit_id}"
    
    doc = {
        "cod_id": cod_id,
        "type": payload.type,
        "status": initial_status,
        "screenshot_url": payload.screenshot_url,
        "product_link": payload.product_link,
        "product_name": product_name,
        "offer_price": offer_price,
        "note": payload.note,
        "location": payload.location,
        "location_address": payload.location_address,
        "location_lat": payload.location_lat,
        "location_lng": payload.location_lng,
        "wa_number": payload.wa_number,
        "trx_id": trx_id_val,
        "unit_id": payload.unit_id if payload.type == "jual" else None,
        "delivery_address": delivery_address,
        "wa_customer": wa_customer,
        "items": items,
        "kasir_id": kasir_id,
        "kasir_name": kasir_name,
        "kurir_id": payload.kurir_id if payload.type != "delivery" else None,
        "kurir_name": kurir_name_val,
        "cabang": cabang,
        "status_history": status_history,
        "created_at": now,
        "updated_at": now,
    }
    
    result = await db.cod_requests.insert_one(doc)
    doc["_id"] = result.inserted_id
    
    await write_log(
        db, actor, "Buat COD Request",
        f"{cod_id} → {payload.type.upper()} {product_name or ''} ({offer_price or 0})",
        cabang
    )
    
    return _format_cod_response(doc)


async def update_cod_status(
    db: AsyncIOMotorDatabase,
    cod_id: str,
    new_status: str,
    actor: str,
    actor_name: str,
    note: Optional[str] = None,
    cabang: Optional[str] = None,
) -> CODRequestResponse:
    """Update status COD. Two paths:
    1. Delivery broadcast accept: atomic claim (kurir_id was None, now assigned)
    2. All other transitions: existing ownership check (kurir_id == actor)
    """
    
    now = datetime.now(timezone.utc)
    
    # ── PATH 1: Atomic claim for delivery broadcast ──
    # When: delivery type, accepting (menunggu_kurir → diterima), kurir_id is null
    if new_status == "diterima":
        result = await db.cod_requests.find_one_and_update(
            {
                "cod_id": cod_id,
                "status": "menunggu_kurir",
                **({"cabang": cabang} if cabang else {}),
                "$or": [
                    {"kurir_id": None},
                    {"kurir_id": {"$exists": False}}
                ]
            },
            {
                "$set": {
                    "status": "diterima",
                    "kurir_id": actor,
                    "kurir_name": actor_name,
                    "updated_at": now
                },
                "$push": {
                    "status_history": {
                        "status": "diterima",
                        "by": actor,
                        "by_name": actor_name,
                        "at": now,
                        "note": note or "Accepted via broadcast"
                    }
                }
            },
            return_document=True
        )
        if result:
            await write_log(
                db, actor, "Accept COD (broadcast)",
                f"{cod_id} → diterima oleh {actor_name}",
                result.get("cabang", "")
            )
            return _format_cod_response(result)
        # If result is None, fall through to path 2 (might be manual-assign accept)
    
    # ── PATH 2: Flow-validated + atomic status update ──
    doc = await db.cod_requests.find_one({"cod_id": cod_id, **({"cabang": cabang} if cabang else {})})
    if not doc:
        raise HTTPException(status_code=404, detail="COD Request tidak ditemukan")
    
    # Validasi hak akses - hanya kurir yang ditugaskan
    if doc.get("kurir_id") != actor:
        raise HTTPException(status_code=403, detail="Bukan kurir yang ditugaskan")
    
    # Validasi transisi status
    current = doc["status"]
    flow = ALL_FLOWS[doc["type"]]
    
    # Idempotency: same request returns current result, except an interrupted
    # delivery rollback which must be resumed safely by the assigned courier.
    if new_status == current:
        if doc["type"] == "delivery" and current == "gagal" and doc.get("rollback_state") != "completed":
            return await _rollback_delivery_failure(db, doc, actor, actor_name, note)
        return _format_cod_response(doc)
    
    if new_status not in flow.get(current, []):
        raise HTTPException(
            status_code=400, 
            detail=f"Transisi status dari '{current}' ke '{new_status}' tidak diizinkan untuk tipe {doc['type']}"
        )

    if doc["type"] == "jual" and new_status == "transaksi_berhasil":
        return await _complete_cod_jual(db, doc, actor, actor_name, note)
    if doc["type"] == "delivery" and new_status == "gagal":
        return await _rollback_delivery_failure(db, doc, actor, actor_name, note)
    
    # Atomic update with status filter to prevent race
    update_result = await db.cod_requests.find_one_and_update(
        {"cod_id": cod_id, "cabang": doc.get("cabang"), "kurir_id": actor, "status": current},
        {"$set": {
            "status": new_status,
            "updated_at": now
        }, "$push": {
            "status_history": {
                "status": new_status,
                "by": actor,
                "by_name": actor_name,
                "at": now,
                "note": note
            }
        }}
    )
    if not update_result:
        raise HTTPException(status_code=409, detail="Status sudah berubah, coba lagi")
    
    doc = await db.cod_requests.find_one({"cod_id": cod_id})
    
    await write_log(
        db, actor, "Update COD Status",
        f"{cod_id} → {current} → {new_status}" + (f" ({note})" if note else ""),
        doc["cabang"]
    )
    
    return _format_cod_response(doc)


async def _complete_cod_jual(
    db: AsyncIOMotorDatabase, doc: dict, actor: str, actor_name: str, note: Optional[str]
) -> CODRequestResponse:
    """Finalize COD Jual exactly once against its existing sale transaction."""
    trx_id, unit_id, cabang = doc.get("trx_id"), doc.get("unit_id"), doc.get("cabang")
    if not trx_id or not unit_id:
        raise HTTPException(status_code=409, detail="COD Jual legacy tidak memiliki relasi transaksi dan unit yang lengkap")
    trx = await db.transaksi.find_one({"trx_id": trx_id, "cabang": cabang})
    unit = await db.units.find_one({"unit_id": unit_id, "cabang": cabang})
    if not trx or trx.get("unit_id") != unit_id or not unit or unit.get("status") != "Sold":
        raise HTTPException(status_code=409, detail="Invariant COD Jual gagal: transaksi dan unit tidak lagi konsisten")
    linked = trx.get("cod_id")
    if linked and linked != doc["cod_id"]:
        raise HTTPException(status_code=409, detail="Transaksi sudah diselesaikan oleh COD lain")

    now = datetime.now(timezone.utc)
    # Penjualan sudah dicatat pada transaksi; penyelesaian COD hanya menandai
    # fulfillment dari transaksi yang sama, bukan menciptakan transaksi kedua.
    linked_result = await db.transaksi.update_one(
        {"trx_id": trx_id, "cabang": cabang, "$or": [{"cod_id": None}, {"cod_id": {"$exists": False}}, {"cod_id": doc["cod_id"]}]},
        {"$set": {"cod_id": doc["cod_id"], "cod_status": "transaksi_berhasil", "fulfillment_status": "completed", "fulfilled_at": now}},
    )
    if not linked_result.matched_count:
        raise HTTPException(status_code=409, detail="Transaksi sudah dikaitkan ke COD lain")
    completed = await db.cod_requests.find_one_and_update(
        {"cod_id": doc["cod_id"], "cabang": cabang, "kurir_id": actor, "status": "kurir_sedang_transaksi"},
        {"$set": {"status": "transaksi_berhasil", "completed_trx_id": trx_id, "completed_unit_id": unit_id, "updated_at": now},
         "$push": {"status_history": {"status": "transaksi_berhasil", "by": actor, "by_name": actor_name, "at": now, "note": note or "Transaksi dan unit telah direkonsiliasi"}}},
        return_document=True,
    )
    if not completed:
        # Request ganda aman: transaksi tetap menunjuk COD yang sama; caller
        # menerima konflik agar tidak menganggap submit kedua sebagai proses baru.
        raise HTTPException(status_code=409, detail="COD Jual sudah berubah status, coba muat ulang")
    await write_log(db, actor, "Selesai COD Jual", f"{doc['cod_id']} → {trx_id} → {unit_id}", cabang)
    return _format_cod_response(completed)


async def _rollback_delivery_failure(
    db: AsyncIOMotorDatabase, doc: dict, actor: str, actor_name: str, note: Optional[str]
) -> CODRequestResponse:
    """Compensate a failed delivery once; retries resume an unfinished rollback."""
    if not doc.get("trx_id"):
        raise HTTPException(status_code=409, detail="COD Delivery tidak memiliki transaksi untuk di-rollback")
    now = datetime.now(timezone.utc)
    claimed = await db.cod_requests.find_one_and_update(
        {"cod_id": doc["cod_id"], "cabang": doc["cabang"], "kurir_id": actor, "status": "sedang_diantar"},
        {"$set": {"status": "gagal", "rollback_state": "processing", "updated_at": now},
         "$push": {"status_history": {"status": "gagal", "by": actor, "by_name": actor_name, "at": now, "note": note or "Delivery gagal; rollback transaksi dimulai"}}},
        return_document=True,
    )
    if not claimed:
        # Retry only resumes the rollback owned by the same courier.
        claimed = await db.cod_requests.find_one({"cod_id": doc["cod_id"], "cabang": doc["cabang"], "kurir_id": actor, "status": "gagal", "rollback_state": {"$in": ["processing", "failed"]}})
        if not claimed:
            raise HTTPException(status_code=409, detail="COD Delivery tidak dapat di-rollback pada status ini")

    trx = await db.transaksi.find_one({"trx_id": claimed["trx_id"], "cabang": claimed["cabang"]})
    if not trx:
        await db.cod_requests.update_one({"cod_id": claimed["cod_id"]}, {"$set": {"rollback_state": "failed", "rollback_error": "Transaksi tidak ditemukan"}})
        raise HTTPException(status_code=409, detail="Transaksi delivery tidak ditemukan")

    # Conditional transaction claim prevents duplicate stock restoration on
    # duplicate submit/concurrent retry.
    transition = await db.transaksi.update_one(
        {"_id": trx["_id"], "$or": [{"fulfillment_status": {"$exists": False}}, {"fulfillment_status": {"$nin": ["rolled_back", "cancelled"]}}]},
        {"$set": {"fulfillment_status": "rolled_back", "cod_status": "gagal", "cancelled_at": now, "cancelled_by_cod": claimed["cod_id"]}},
    )
    if transition.modified_count:
        if trx.get("unit_id"):
            await db.units.update_one(
                {"unit_id": trx["unit_id"], "cabang": claimed["cabang"], "status": "Sold"},
                {"$set": {"status": "Tersedia", "tgl_terjual": None, "updated_at": now, "rollback_cod_id": claimed["cod_id"]}},
            )
        for item in trx.get("sp_items") or []:
            qty = item.get("jumlah", 0)
            if qty > 0:
                await db.sparepart.update_one(
                    {"sp_id": item.get("sp_id"), "cabang": claimed["cabang"]},
                    {"$inc": {"stok": qty}, "$set": {"updated_at": now, "rollback_cod_id": claimed["cod_id"]}},
                )

    await db.cod_requests.update_one(
        {"cod_id": claimed["cod_id"], "status": "gagal"},
        {"$set": {"rollback_state": "completed", "rolled_back_at": now}},
    )
    completed = await db.cod_requests.find_one({"cod_id": claimed["cod_id"]})
    await write_log(db, actor, "Rollback COD Delivery", f"{claimed['cod_id']} → {claimed['trx_id']}", claimed["cabang"])
    return _format_cod_response(completed)


async def list_cod_requests(
    db: AsyncIOMotorDatabase,
    cabang: str,
    kurir_id: str,
    kurir_name: str,
    status: Optional[str] = None,
    type_filter: Optional[str] = None,
    limit: int = 25,
    skip: int = 0,
) -> List[CODRequestList]:
    """Dashboard Kurir: list COD assigned ke kurir ini + broadcast delivery."""
    
    query = {
        "cabang": cabang,
        "$or": [
            {"kurir_id": kurir_id},  # assigned to me
            {"kurir_id": None, "type": {"$in": ["delivery", "beli"]}, "status": "menunggu_kurir"}  # broadcast
        ]
    }
    if status:
        query["status"] = status
    if type_filter:
        query["type"] = type_filter
    
    cursor = db.cod_requests.find(query).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    
    return [_format_dashboard_item(d) for d in docs]


async def list_cod_requests_all(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str],
    status: Optional[str] = None,
    type_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    kasir_id: Optional[str] = None
) -> List[CODRequestList]:
    """List COD untuk Kasir/KC/Owner."""
    
    query = {}
    if cabang:
        query["cabang"] = cabang
    # Only apply kasir_id filter if NOT filtering for menunggu_approval_kasir
    # Kasir needs to see ALL pending approvals in their cabang
    if kasir_id and status != "menunggu_approval_kasir":
        query["kasir_id"] = kasir_id
    if status:
        query["status"] = status
    if type_filter:
        query["type"] = type_filter
    if date_from or date_to:
        from datetime import datetime, timezone, timedelta
        wf = {}
        if date_from:
            wf["$gte"] = datetime.fromisoformat(date_from.replace("Z", "")).replace(tzinfo=timezone.utc)
        if date_to:
            # Make date_to inclusive by adding 1 day
            dt = datetime.fromisoformat(date_to.replace("Z", "")).replace(tzinfo=timezone.utc) + timedelta(days=1)
            wf["$lt"] = dt
        query["created_at"] = wf
    
    cursor = db.cod_requests.find(query).sort("created_at", -1).limit(limit)
    docs = await cursor.to_list(length=limit)
    
    return [_format_dashboard_item(d) for d in docs]


async def get_cod_detail(
    db: AsyncIOMotorDatabase,
    cod_id: str,
    cabang: Optional[str] = None,
) -> CODRequestDetail:
    """Get detail COD request."""

    query = {"cod_id": cod_id}
    if cabang:
        query["cabang"] = cabang
    doc = await db.cod_requests.find_one(query)
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
        trx_id=doc.get("trx_id") or doc.get("transaksi_id"),  # backward compat
        unit_id=doc.get("unit_id"),
        delivery_address=doc.get("delivery_address"),
        wa_customer=doc.get("wa_customer"),
        items=doc.get("items"),
        kasir_id=doc["kasir_id"],
        kasir_name=doc["kasir_name"],
        kurir_id=doc.get("kurir_id"),
        kurir_name=doc.get("kurir_name"),
        status_history=doc.get("status_history") or [],
    )


async def get_kurir_list(db: AsyncIOMotorDatabase, cabang: str) -> List[KurirListItem]:
    """List kurir aktif di cabang."""
    cursor = db.users.find({"role": "Kurir", "cabang": cabang, "aktif": True})
    kurirs = await cursor.to_list(length=None)
    return [KurirListItem(kurir_id=k["username"], kurir_name=k.get("name", k["username"]), cabang=k["cabang"]) for k in kurirs]


async def approve_beli_cod(
    db: AsyncIOMotorDatabase,
    cod_id: str,
    kasir_name: str,
    cabang: str,
    harga_jual: int = 0,
    unit_data: Dict[str, Any] = None,
    garansi_toko: int = 7,
    catatan: str = "",
) -> CODRequestResponse:
    """
    Kasir approve COD beli — atomic claim → validate → create unit → finalize.
    Double-click safe via atomic processing_approval claim.
    Reverts to menunggu_approval_kasir on any failure.
    """
    now = datetime.now(timezone.utc)

    # ══ Step 1: Atomic claim — prevents double-click ══
    doc = await db.cod_requests.find_one_and_update(
        {
            "cod_id": cod_id,
            "status": "menunggu_approval_kasir",
            "type": "beli",
            "cabang": cabang,
        },
        {
            "$set": {
                "status": "processing_approval",
                "updated_at": now,
            },
            "$push": {
                "status_history": {
                    "status": "processing_approval",
                    "by": kasir_name,
                    "at": now,
                    "note": "Processing approval"
                }
            }
        },
        return_document=True,
    )

    if not doc:
        raise HTTPException(status_code=409, detail="COD sudah diapprove atau tidak dalam status menunggu approval")

    # ══ Helper: revert status on failure ══
    async def _revert(reason: str):
        await db.cod_requests.update_one(
            {"cod_id": cod_id, "status": "processing_approval"},
            {"$set": {"status": "menunggu_approval_kasir", "updated_at": datetime.now(timezone.utc)}}
        )
        await write_log(db, kasir_name, "Gagal Approve COD Beli", f"{cod_id}: {reason}", cabang)

    # ══ Step 2: Validate unit_data ══
    # Use unit_data from request if provided (kasir edited), otherwise fallback to COD doc
    final_unit_data = unit_data or doc.get("unit_data", {})
    if not final_unit_data:
        await _revert("Data unit tidak ditemukan di COD")
        raise HTTPException(status_code=400, detail="Data unit tidak ditemukan di COD")

    # ══ Step 3: Create unit ══
    from app.utils.id_generator import next_unit_id
    from app.services.unit_service import route_unit_to_inventory_or_service

    kat_kode = final_unit_data.get("kat_kode", "AI")
    kondisi_kode = final_unit_data.get("kondisi_kode", "BN")
    unit_id = await next_unit_id(db, kat_kode, kondisi_kode, cabang)

    kondisi_hp = final_unit_data.get("kondisi_hp", "Mulus")
    deal_price = doc.get("deal_price", 0)

    unit_doc = {
        "unit_id": unit_id,
        "merk": final_unit_data.get("merk", ""),
        "tipe": final_unit_data.get("tipe", ""),
        "storage": final_unit_data.get("storage", "-"),
        "ram": final_unit_data.get("ram", "-"),
        "warna": final_unit_data.get("warna", "-"),
        "imei": final_unit_data.get("imei", "-"),
        "imei2": final_unit_data.get("imei2", "-"),
        "tipe_sim": final_unit_data.get("tipe_sim", "Single SIM"),
        "keamanan": final_unit_data.get("keamanan", "Tidak Ada"),
        "speaker": final_unit_data.get("speaker", "Normal"),
        "lcd": final_unit_data.get("lcd", "Original"),
        "harga_modal": deal_price,
        "harga_jual": 0 if kondisi_hp == "Repair" else harga_jual,
        "kondisi": final_unit_data.get("kondisi", "Normal"),
        "kondisi_hp": kondisi_hp,
        "battery": final_unit_data.get("battery", 100),
        "battery_health": final_unit_data.get("battery_health", 0),
        "status": "Service" if kondisi_hp == "Repair" else "Tersedia",
        "kategori": final_unit_data.get("kategori", "Android"),
        "catatan": catatan or f"COD Beli {doc['cod_id']}",
        "cabang": cabang,
        "locked": True,
        "garansi_toko": garansi_toko,
        "created_at": now,
        "created_by": kasir_name,
        "tgl_terjual": None,
        "service_id": None,
        "foto_url": final_unit_data.get("foto_url"),
        "input_by_role": "Kurir (COD Beli) → Approved by Kasir",
    }

    try:
        await db.units.insert_one(unit_doc)
    except Exception as e:
        await _revert(f"Gagal membuat unit: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Gagal membuat unit: {str(e)}")

    # ══ Step 4: Route to inventory or service ══
    try:
        unit_label = f"{unit_doc['merk']} {unit_doc['tipe']} {unit_doc['storage']}"
        await route_unit_to_inventory_or_service(
            db, unit_id, unit_label, kondisi_hp, cabang, kasir_name,
            keluhan=final_unit_data.get("keluhan", "")
        )
    except Exception as e:
        await _revert(f"Gagal routing unit: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Gagal routing unit: {str(e)}")

    # ══ Step 5: Finalize — set selesai + store unit_id ══
    now_final = datetime.now(timezone.utc)
    await db.cod_requests.update_one(
        {"cod_id": cod_id, "status": "processing_approval"},
        {
            "$set": {
                "status": "selesai",
                "approved_by": kasir_name,
                "approved_at": now_final,
                "updated_at": now_final,
                "unit_id": unit_id,
            },
            "$push": {
                "status_history": {
                    "status": "selesai",
                    "by": kasir_name,
                    "at": now_final,
                    "note": f"Approved — Unit {unit_id} ({kondisi_hp})"
                }
            }
        }
    )

    await write_log(
        db, kasir_name, "Approve COD Beli",
        f"{doc['cod_id']} → Unit {unit_id} ({kondisi_hp}) → {'Tersedia' if kondisi_hp != 'Repair' else 'Service'}",
        cabang
    )

    return _format_cod_response(await db.cod_requests.find_one({"cod_id": cod_id}))


async def reject_beli_cod(
    db: AsyncIOMotorDatabase,
    cod_id: str,
    reason: str,
    kasir_name: str,
    cabang: str,
) -> CODRequestResponse:
    """Kasir reject COD beli with reason."""
    now = datetime.now(timezone.utc)
    
    doc = await db.cod_requests.find_one_and_update(
        {
            "cod_id": cod_id,
            "status": "menunggu_approval_kasir",
            "type": "beli",
            "cabang": cabang,  # Validate cabang ownership
        },
        {
            "$set": {
                "status": "ditolak",
                "reject_reason": reason,
                "updated_at": now,
            },
            "$push": {
                "status_history": {
                    "status": "ditolak",
                    "by": kasir_name,
                    "at": now,
                    "note": reason
                }
            }
        },
        return_document=True
    )
    
    if not doc:
        raise HTTPException(status_code=409, detail="COD tidak dalam status menunggu approval")
    
    await write_log(
        db, kasir_name, "Reject COD Beli",
        f"{cod_id} → Ditolak: {reason}",
        cabang
    )
    
    return _format_cod_response(doc)


async def reject_beli_by_kurir(
    db: AsyncIOMotorDatabase,
    cod_id: str,
    kurir_id: str,
    kurir_name: str,
    reason: str,
) -> CODRequestResponse:
    """Kurir reject COD beli setelah bertemu penjual (status sudah_bertemu_penjual)."""
    now = datetime.now(timezone.utc)

    doc = await db.cod_requests.find_one_and_update(
        {
            "cod_id": cod_id,
            "status": "sudah_bertemu_penjual",
            "type": "beli",
            "kurir_id": kurir_id,
        },
        {
            "$set": {
                "status": "ditolak",
                "reject_reason": reason,
                "updated_at": now,
            },
            "$push": {
                "status_history": {
                    "status": "ditolak",
                    "by": kurir_id,
                    "by_name": kurir_name,
                    "at": now,
                    "note": f"Ditolak kurir: {reason}"
                }
            }
        },
        return_document=True
    )

    if not doc:
        raise HTTPException(status_code=409, detail="COD tidak bisa ditolak — status atau kurir tidak sesuai")

    await write_log(
        db, kurir_name, "Reject COD Beli (Kurir)",
        f"{cod_id} → Ditolak kurir: {reason}",
        doc.get("cabang", "")
    )

    return _format_cod_response(doc)


async def submit_kurir_beli(
    db: AsyncIOMotorDatabase,
    cod_id: str,
    kurir_id: str,
    kurir_name: str,
    deal_price: int,
    unit_data: dict,
) -> CODRequestResponse:
    """Kurir submit data HP setelah bertemu penjual (type=beli)."""
    from app.utils.upload_urls import ensure_uploaded_asset
    ensure_uploaded_asset(unit_data.get("foto_url"), "foto_url")
    now = datetime.now(timezone.utc)
    
    doc = await db.cod_requests.find_one_and_update(
        {
            "cod_id": cod_id,
            "status": "sudah_bertemu_penjual",
            "kurir_id": kurir_id,
        },
        {
            "$set": {
                "status": "menunggu_approval_kasir",
                "deal_price": deal_price,
                "unit_data": unit_data,
                "updated_at": now,
            },
            "$push": {
                "status_history": {
                    "status": "menunggu_approval_kasir",
                    "by": kurir_id,
                    "by_name": kurir_name,
                    "at": now,
                    "note": f"Deal price: {deal_price}"
                }
            }
        },
        return_document=True
    )
    
    if not doc:
        raise HTTPException(status_code=409, detail="COD tidak bisa disubmit — status atau kurir tidak sesuai")
    
    await write_log(
        db, kurir_name, "Submit COD Beli",
        f"{cod_id} → Deal {deal_price} • {unit_data.get('merk', '')} {unit_data.get('tipe', '')}",
        doc.get("cabang", "")
    )
    
    return _format_cod_response(doc)


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
        location=doc.get("location", ""),
        wa_number=doc.get("wa_number", ""),
        screenshot_url=doc.get("screenshot_url", ""),
        product_name=doc.get("product_name"),
        offer_price=doc.get("offer_price"),
        kasir_name=doc.get("kasir_name", ""),
        kurir_name=doc.get("kurir_name"),
        kurir_id=doc.get("kurir_id"),
        delivery_address=doc.get("delivery_address"),
        wa_customer=doc.get("wa_customer"),
        items=doc.get("items"),
        # Beli-specific
        unit_data=doc.get("unit_data"),
        deal_price=doc.get("deal_price"),
        reject_reason=doc.get("reject_reason"),
    )


async def get_kurir_monitoring(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
) -> List[dict]:
    """
    Get kurir monitoring stats per cabang for Owner/Kepala Cabang.
    Returns list of kurir with their COD stats.
    """
    query = {}
    if cabang:
        query["cabang"] = cabang
    
    # Date filter
    if date_from or date_to:
        from datetime import datetime, timezone, timedelta
        wf = {}
        if date_from:
            wf["$gte"] = datetime.fromisoformat(date_from.replace("Z", "")).replace(tzinfo=timezone.utc)
        if date_to:
            # Make date_to inclusive by adding 1 day
            dt = datetime.fromisoformat(date_to.replace("Z", "")).replace(tzinfo=timezone.utc) + timedelta(days=1)
            wf["$lt"] = dt
        query["created_at"] = wf
    
    # Aggregate by kurir
    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$kurir_id",
            "kurir_name": {"$first": "$kurir_name"},
            "cabang": {"$first": "$cabang"},
            "total_cod": {"$sum": 1},
            "cod_beli": {"$sum": {"$cond": [{"$eq": ["$type", "beli"]}, 1, 0]}},
            "cod_jual": {"$sum": {"$cond": [{"$eq": ["$type", "jual"]}, 1, 0]}},
            "status_menunggu": {"$sum": {"$cond": [{"$eq": ["$status", "menunggu_kurir"]}, 1, 0]}},
            "status_diterima": {"$sum": {"$cond": [{"$eq": ["$status", "diterima"]}, 1, 0]}},
            "status_proses": {
                "$sum": {
                    "$cond": [
                        {"$in": ["$status", ["diterima", "kurir_menuju_lokasi", "sudah_bertemu_penjual", "barang_akan_dijemput", "barang_sudah_diambil", "kurir_sedang_transaksi"]]},
                        1, 0
                    ]
                }
            },
            "status_selesai": {"$sum": {"$cond": [{"$eq": ["$status", "selesai"]}, 1, 0]}},
            "status_transaksi_berhasil": {"$sum": {"$cond": [{"$eq": ["$status", "transaksi_berhasil"]}, 1, 0]}},
            "status_gagal": {"$sum": {"$cond": [{"$eq": ["$status", "gagal"]}, 1, 0]}},
            "status_ditolak": {"$sum": {"$cond": [{"$eq": ["$status", "ditolak"]}, 1, 0]}},
            "total_offer_price": {"$sum": {"$cond": [{"$eq": ["$type", "beli"]}, "$offer_price", 0]}},
            "total_transaksi_price": {"$sum": {"$cond": [{"$eq": ["$type", "jual"]}, "$offer_price", 0]}},
            "last_activity": {"$max": "$updated_at"},
            "first_activity": {"$min": "$created_at"},
        }},
        {"$sort": {"total_cod": -1}},
    ]
    
    cursor = db.cod_requests.aggregate(pipeline)
    results = await cursor.to_list(length=None)
    
    # Format response
    formatted = []
    for r in results:
        # Calculate success rate
        total_done = r.get("status_selesai", 0) + r.get("status_transaksi_berhasil", 0)
        total_assigned = r.get("total_cod", 0) - r.get("status_menunggu", 0) - r.get("status_ditolak", 0)
        success_rate = round((total_done / total_assigned * 100), 1) if total_assigned > 0 else 0
        
        formatted.append({
            "kurir_id": r["_id"],
            "kurir_name": r.get("kurir_name", r["_id"]),
            "cabang": r.get("cabang"),
            "total_cod": r.get("total_cod", 0),
            "cod_beli": r.get("cod_beli", 0),
            "cod_jual": r.get("cod_jual", 0),
            "status_menunggu": r.get("status_menunggu", 0),
            "status_diterima": r.get("status_diterima", 0),
            "status_proses": r.get("status_proses", 0),
            "status_selesai": r.get("status_selesai", 0),
            "status_transaksi_berhasil": r.get("status_transaksi_berhasil", 0),
            "status_gagal": r.get("status_gagal", 0),
            "status_ditolak": r.get("status_ditolak", 0),
            "success_rate": success_rate,
            "total_offer_price": r.get("total_offer_price", 0),
            "total_transaksi_price": r.get("total_transaksi_price", 0),
            "last_activity": r.get("last_activity"),
            "first_activity": r.get("first_activity"),
        })
    
    return formatted