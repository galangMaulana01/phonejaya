from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from bson import ObjectId

from app.schemas.request_sparepart import (
    RequestSparepartCreateRequest, RequestSparepartResponseRequest, RequestSparepartResponse,
    RequestSparepartApproveRequest, StatusRequestEnum
)
from app.services.log_service import write_log
from app.utils.formatters import fmt_waktu


def _fmt(doc: dict) -> RequestSparepartResponse:
    return RequestSparepartResponse(
        id=str(doc["_id"]), req_id=doc.get("req_id", str(doc["_id"])),
        tipe=doc.get("tipe",""), service_id=doc.get("service_id"),
        unit_id=doc.get("unit_id"),
        sp_id=doc.get("sp_id"),
        nama_sp=doc.get("nama_sp",""), jumlah=doc.get("jumlah",1),
        keterangan=doc.get("keterangan",""), status=doc.get("status","Pending"),
        estimasi_tiba=doc.get("estimasi_tiba"), catatan_kc=doc.get("catatan_kc",""),
        harga_jual=doc.get("harga_jual"),
        product_link=doc.get("product_link"),
        cabang=doc.get("cabang",""), dibuat_oleh=doc.get("dibuat_oleh",""),
        disetujui_oleh_kc=doc.get("disetujui_oleh_kc"),
        disetujui_at_kc=fmt_waktu(doc["disetujui_at_kc"]) if doc.get("disetujui_at_kc") else None,
        approved_by=doc.get("approved_by"),
        approved_at=fmt_waktu(doc["approved_at"]) if doc.get("approved_at") else None,
        created_at=fmt_waktu(doc["created_at"]) if doc.get("created_at") else "",
        updated_at=fmt_waktu(doc["updated_at"]) if doc.get("updated_at") else None,
        # Snapshot fields
        harga_modal_snapshot=doc.get("harga_modal_snapshot"),
        unit_nama_snapshot=doc.get("unit_nama_snapshot"),
    )


async def _next_req_id(db) -> str:
    res = await db.counters.find_one_and_update(
        {"_id": "REQ_SP"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True,
    )
    return f"REQ-SP-{str(res['seq']).zfill(3)}"


async def list_requests(db, cabang=None, status=None) -> List[RequestSparepartResponse]:
    query: dict = {}
    if cabang: query["cabang"] = cabang
    if status: query["status"] = status
    docs = await db.request_sparepart.find(query).sort("created_at", -1).to_list(length=100)
    return [_fmt(d) for d in docs]


async def create_request(
    db, payload: RequestSparepartCreateRequest, actor: str, actor_id: str
) -> RequestSparepartResponse:
    """
    Teknisi create request sparepart untuk service tertentu.
    Validasi:
    - service_id WAJIB untuk request baru
    - service status = Proses atau Selesai (sudah dipegang teknisi)
    - service.teknisi == actor (teknisi yang pegang)
    - service.cabang == payload.cabang
    - Kalau sp_id null (beli baru) -> product_link WAJIB
    """
    # Validasi service_id wajib untuk request baru
    if not payload.service_id or not payload.service_id.strip():
        raise HTTPException(status_code=400, detail="Wajib pilih tiket servis yang berkaitan (service_id)")

    # Validasi service
    svc = await db.service.find_one({"service_id": payload.service_id})
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service {payload.service_id} tidak ditemukan")

    if svc.get("status") not in ("Proses", "Selesai"):
        raise HTTPException(
            status_code=400,
            detail=f"Service status {svc.get('status')} tidak bisa request sparepart. Harus Proses atau Selesai."
        )

    if svc.get("teknisi") != actor:
        raise HTTPException(
            status_code=403,
            detail="Hanya teknisi yang sedang mengerjakan service ini yang boleh request sparepart"
        )

    if svc.get("cabang") != payload.cabang:
        raise HTTPException(status_code=403, detail="Service bukan cabang Anda")

    # Validasi product_link kalau beli baru (sp_id null)
    if not payload.sp_id and (not payload.product_link or not payload.product_link.strip()):
        raise HTTPException(status_code=400, detail="Link produk wajib diisi jika sparepart belum ada di stok (sp_id kosong)")

    # Validasi sparepart existing kalau sp_id terisi
    if payload.sp_id:
        sp = await db.sparepart.find_one({"sp_id": payload.sp_id, "cabang": payload.cabang})
        if not sp:
            raise HTTPException(status_code=404, detail=f"Sparepart {payload.sp_id} tidak ditemukan di cabang ini")

    req_id = await _next_req_id(db)
    now = datetime.now(timezone.utc)

    unit_id = svc.get("unit_id")
    unit_doc = None
    if unit_id:
        unit_doc = await db.units.find_one({"unit_id": unit_id})

    doc = {
        "req_id": req_id, "tipe": payload.tipe, "service_id": payload.service_id,
        "unit_id": unit_id,
        "sp_id": payload.sp_id,
        "nama_sp": payload.nama_sp, "jumlah": payload.jumlah,
        "keterangan": payload.keterangan, "status": "Pending",
        "estimasi_tiba": None, "catatan_kc": "",
        "harga_jual": None,
        "product_link": payload.product_link,
        "cabang": payload.cabang, "dibuat_oleh": actor,
        "disetujui_oleh_kc": None, "disetujui_at_kc": None,
        "approved_by": None, "approved_at": None,
        "created_at": now, "updated_at": None,
        # Snapshot fields
        "harga_modal_snapshot": unit_doc.get("harga_modal") if unit_doc else None,
        "unit_nama_snapshot": f"{unit_doc.get('merk')} {unit_doc.get('tipe')}" if unit_doc else None,
    }
    res = await db.request_sparepart.insert_one(doc)
    doc["_id"] = res.inserted_id

    await write_log(db, actor_id, "Request Sparepart", f"{req_id} • {payload.nama_sp} x{payload.jumlah} (Service: {payload.service_id})", payload.cabang)
    return _fmt(doc)


async def respond_request(
    db, req_id: str, payload: RequestSparepartResponseRequest,
    actor: str, actor_role: str = '', actor_cabang: str = ''
) -> RequestSparepartResponse:
    """Kepala Cabang respond: Diterima -> Menunggu_Kasir + estimasi, Ditolak -> Ditolak"""
    doc = await db.request_sparepart.find_one({"req_id": req_id})
    if not doc: raise HTTPException(404, f"Request {req_id} tidak ditemukan")
    if doc["status"] != "Pending": raise HTTPException(400, "Request sudah direspon")
    if actor_role == 'kepala_cabang' and doc.get('cabang') != actor_cabang:
        raise HTTPException(status_code=403, detail='Kamu tidak bisa respon request cabang lain')

    now = datetime.now(timezone.utc)
    update = {"updated_at": now, "catatan_kc": payload.catatan}

    if payload.status.value == "Diterima":
        update["status"] = "Menunggu_Kasir"
        update["disetujui_oleh_kc"] = actor
        update["disetujui_at_kc"] = now
        if payload.estimasi_tiba:
            update["estimasi_tiba"] = payload.estimasi_tiba
    elif payload.status.value == "Ditolak":
        update["status"] = "Ditolak"

    await db.request_sparepart.update_one({"req_id": req_id}, {"$set": update})
    updated = await db.request_sparepart.find_one({"req_id": req_id})

    await write_log(db, actor, "Respon Request Sparepart", f"{req_id} → {update.get('status', 'updated')}", doc.get("cabang",""))
    return _fmt(updated)


async def approve_request(
    db, req_id: str, payload: RequestSparepartApproveRequest,
    actor: str, actor_role: str = '', actor_cabang: str = ''
) -> RequestSparepartResponse:
    """
    Kasir final approval:
    - Status Selesai: set harga_jual, create/update sparepart master, atomic $inc harga_modal unit, log via write_log
    - Status Ditolak: set status Ditolak
    Atomic: pakai find_one_and_update dengan filter status=Menunggu_Kasir untuk prevent double approve
    """
    if actor_role != "kasir":
        raise HTTPException(403, "Hanya Kasir yang bisa melakukan approval akhir")

    # Atomic claim: prevent double-click
    now = datetime.now(timezone.utc)
    doc = await db.request_sparepart.find_one_and_update(
        {"req_id": req_id, "status": "Menunggu_Kasir", "cabang": actor_cabang},
        {"$set": {"status": "processing_approval", "updated_at": now}},
        return_document=True
    )
    if not doc:
        raise HTTPException(409, "Request tidak dalam status Menunggu_Kasir atau sudah diproses")

    try:
        # Get unit info
        unit_id = doc.get("unit_id")
        service_id = doc.get("service_id")
        unit_doc = None
        if unit_id:
            unit_doc = await db.units.find_one({"unit_id": unit_id})
            if not unit_doc:
                # Rollback status
                await db.request_sparepart.update_one(
                    {"req_id": req_id, "status": "processing_approval"},
                    {"$set": {"status": "Menunggu_Kasir", "updated_at": datetime.now(timezone.utc)}}
                )
                raise HTTPException(404, f"Unit {unit_id} tidak ditemukan")

        # Process approval
        if payload.status == "Selesai":
            if payload.harga_jual <= 0:
                # Rollback
                await db.request_sparepart.update_one(
                    {"req_id": req_id, "status": "processing_approval"},
                    {"$set": {"status": "Menunggu_Kasir", "updated_at": datetime.now(timezone.utc)}}
                )
                raise HTTPException(400, "Harga jual harus diisi untuk status Selesai")

            # Create/Update sparepart master
            if doc.get("sp_id"):
                # Existing sparepart: update stok + harga_jual
                from app.services.sparepart import create_sparepart, update_stok
                from app.schemas.sparepart import SparepartCreateRequest, SparepartUpdateStokRequest

                existing_sp = await db.sparepart.find_one({"sp_id": doc["sp_id"], "cabang": doc["cabang"]})
                if existing_sp:
                    # Update stok
                    await update_stok(db, doc["sp_id"], SparepartUpdateStokRequest(
                        delta=doc["jumlah"],
                        catatan=f"Approve request {req_id}"
                    ), actor=actor, user_role=actor_role, user_cabang=actor_cabang)
                    # Update harga_jual if different
                    if existing_sp.get("harga_jual") != payload.harga_jual:
                        await db.sparepart.update_one(
                            {"sp_id": doc["sp_id"], "cabang": doc["cabang"]},
                            {"$set": {"harga_jual": payload.harga_jual, "updated_at": datetime.now(timezone.utc)}}
                        )
                    sp_id = doc["sp_id"]
                else:
                    # Create new sparepart (sp_id existed in request but not in master - should not happen)
                    sp_id = None
            else:
                # New sparepart: create new
                from app.services.sparepart import create_sparepart
                from app.schemas.sparepart import SparepartCreateRequest

                try:
                    new_sp = await create_sparepart(db, SparepartCreateRequest(
                        nama=doc["nama_sp"],
                        kategori="Sparepart",
                        satuan="pcs",
                        stok=doc["jumlah"],
                        harga_beli=0,
                        harga_jual=payload.harga_jual,
                        cabang=doc["cabang"],
                        catatan=f"Auto-created from request {req_id}",
                        product_link=doc.get("product_link")
                    ), actor=actor)
                    sp_id = new_sp.sp_id
                    # Update request with sp_id
                    await db.request_sparepart.update_one(
                        {"req_id": req_id, "status": "processing_approval"},
                        {"$set": {"sp_id": sp_id}}
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    # Log the specific error from create_sparepart
                    import traceback
                    error_msg = f"create_sparepart failed: {str(e)}\n{traceback.format_exc()}"
                    await write_log(db, actor, "Error Create Sparepart", error_msg, doc.get("cabang", ""))
                    raise HTTPException(500, f"Failed to create sparepart: {str(e)}")
                sp_id = new_sp.sp_id
                # Update request with sp_id
                await db.request_sparepart.update_one(
                    {"req_id": req_id, "status": "processing_approval"},
                    {"$set": {"sp_id": sp_id}}
                )

            # Atomic $inc harga_modal unit
            if unit_id:
                old_modal = unit_doc.get("harga_modal", 0)
                delta = payload.harga_jual * doc["jumlah"]
                new_modal = old_modal + delta

                await db.units.update_one(
                    {"unit_id": unit_id},
                    {"$inc": {"harga_modal": delta}, "$set": {"updated_at": datetime.now(timezone.utc)}}
                )

                # Log modal history via write_log (known limitation: no rollback on rejection/revision)
                await write_log(
                    db, actor, "Update Modal Sparepart",
                    f"Unit {unit_id} modal +Rp{delta:,} (dari Rp{old_modal:,} -> Rp{new_modal:,}) via sparepart {doc['nama_sp']} x{doc['jumlah']} @ Rp{payload.harga_jual:,} (ref: {req_id})",
                    doc.get("cabang", "")
                )
                # TODO: Rollback logic for rejection/revision not implemented (known limitation)

            # Finalize request
            final_update = {
                "status": "Selesai",
                "harga_jual": payload.harga_jual,
                "approved_by": actor,
                "approved_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "catatan_kc": doc.get("catatan_kc", "") + (" | " + payload.catatan if payload.catatan else ""),
            }
        elif payload.status == "Ditolak":
            final_update = {
                "status": "Ditolak",
                "updated_at": datetime.now(timezone.utc),
                "catatan_kc": doc.get("catatan_kc", "") + (" | " + payload.catatan if payload.catatan else ""),
            }
        else:
            # Rollback
            await db.request_sparepart.update_one(
                {"req_id": req_id, "status": "processing_approval"},
                {"$set": {"status": "Menunggu_Kasir", "updated_at": datetime.now(timezone.utc)}}
            )
            raise HTTPException(400, "Status tidak valid")

        await db.request_sparepart.update_one(
            {"req_id": req_id, "status": "processing_approval"},
            {"$set": final_update}
        )

        updated = await db.request_sparepart.find_one({"req_id": req_id})

        await write_log(db, actor, "Approval Sparepart Kasir", f"{req_id} → {final_update['status']}", doc.get("cabang",""))
        return _fmt(updated)
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Rollback on any unexpected error
        await db.request_sparepart.update_one(
            {"req_id": req_id, "status": "processing_approval"},
            {"$set": {"status": "Menunggu_Kasir", "updated_at": datetime.now(timezone.utc)}}
        )
        # Log the actual error for debugging
        import traceback
        error_msg = f"Approve error: {str(e)}\n{traceback.format_exc()}"
        await write_log(db, actor, "Error Approve Sparepart", error_msg, doc.get("cabang", ""))
        # Re-raise with actual error message for debugging
        raise HTTPException(500, f"Internal server error: {str(e)}")


async def get_request_detail(db, req_id: str) -> RequestSparepartResponse:
    """Get detail request sparepart by req_id"""
    doc = await db.request_sparepart.find_one({"req_id": req_id})
    if not doc:
        raise HTTPException(404, f"Request {req_id} tidak ditemukan")
    return _fmt(doc)