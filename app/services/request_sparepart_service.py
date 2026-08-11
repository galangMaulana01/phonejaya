from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.request_sparepart import (
    RequestSparepartCreateRequest, RequestSparepartResponseRequest, RequestSparepartResponse,
    RequestSparepartBeliRequest, RequestSparepartTerimaRequest,
)
from app.services.log_service import write_log
from app.utils.formatters import fmt_waktu


def _fmt(doc: dict) -> RequestSparepartResponse:
    return RequestSparepartResponse(
        id=str(doc["_id"]), req_id=doc.get("req_id", str(doc["_id"])),
        tipe=doc.get("tipe",""), jenis=doc.get("jenis") or "repair",
        service_id=doc.get("service_id"),
        unit_id=doc.get("unit_id"),
        sp_id=doc.get("sp_id"),
        nama_sp=doc.get("nama_sp",""), jumlah=doc.get("jumlah",1),
        harga_diajukan=doc.get("harga_diajukan"), alasan=doc.get("alasan") or "",
        keterangan=doc.get("keterangan",""), status=doc.get("status","Pending"),
        estimasi_tiba=doc.get("estimasi_tiba"), catatan_kc=doc.get("catatan_kc",""),
        harga_disetujui=doc.get("harga_disetujui"),
        supplier=doc.get("supplier"), harga_beli_aktual=doc.get("harga_beli_aktual"),
        bukti_url=doc.get("bukti_url"), catatan_beli=doc.get("catatan_beli"),
        dibeli_oleh=doc.get("dibeli_oleh"),
        dibeli_at=fmt_waktu(doc["dibeli_at"]) if doc.get("dibeli_at") else None,
        tanggal_terima=doc.get("tanggal_terima"),
        diterima_oleh=doc.get("diterima_oleh"),
        diterima_at=fmt_waktu(doc["diterima_at"]) if doc.get("diterima_at") else None,
        product_link=doc.get("product_link"),
        cabang=doc.get("cabang",""), dibuat_oleh=doc.get("dibuat_oleh",""),
        disetujui_oleh_kc=doc.get("disetujui_oleh_kc"),
        disetujui_at_kc=fmt_waktu(doc["disetujui_at_kc"]) if doc.get("disetujui_at_kc") else None,
        created_at=fmt_waktu(doc["created_at"]) if doc.get("created_at") else "",
        updated_at=fmt_waktu(doc["updated_at"]) if doc.get("updated_at") else None,
        # Snapshot fields
        harga_modal_snapshot=doc.get("harga_modal_snapshot"),
        unit_nama_snapshot=doc.get("unit_nama_snapshot"),
        # Legacy
        harga_jual=doc.get("harga_jual"),
        approved_by=doc.get("approved_by"),
        approved_at=fmt_waktu(doc["approved_at"]) if doc.get("approved_at") else None,
    )


async def _next_req_id(db) -> str:
    res = await db.counters.find_one_and_update(
        {"_id": "REQ_SP"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True,
    )
    return f"REQ-SP-{str(res['seq']).zfill(3)}"


async def _clear_menunggu_sparepart_if_unblocked(db, service_id: str) -> None:
    """Kalau tidak ada lagi request repair yang masih aktif (belum
    Diterima/Digunakan/Ditolak) buat tiket ini, balikin status tiket dari
    Menunggu_Sparepart ke Proses."""
    if not service_id:
        return
    still_blocking = await db.request_sparepart.find_one({
        "service_id": service_id, "jenis": "repair",
        "status": {"$nin": ["Diterima", "Digunakan", "Ditolak"]},
    })
    if still_blocking:
        return
    await db.service.update_one(
        {"service_id": service_id, "status": "Menunggu_Sparepart"},
        {"$set": {"status": "Proses", "updated_at": datetime.now(timezone.utc)}}
    )


async def list_requests(db, cabang=None, status=None) -> List[RequestSparepartResponse]:
    query: dict = {}
    if cabang: query["cabang"] = cabang
    if status: query["status"] = status
    docs = await db.request_sparepart.find(query).sort("created_at", -1).to_list(length=100)
    return [_fmt(d) for d in docs]


async def create_request(
    db, payload: RequestSparepartCreateRequest, actor: str
) -> RequestSparepartResponse:
    """
    Teknisi ajukan request sparepart dengan harga diajukan + alasan.
    - jenis=repair: WAJIB terkait tiket service yang sedang dia kerjakan
      (status Proses), dan tiket itu langsung ditandai Menunggu_Sparepart.
    - jenis=equipment: alat kerja, tidak terkait tiket manapun.
    - Kalau sp_id null (beli baru) -> product_link WAJIB.
    """
    svc = None
    unit_id = None
    service_id = payload.service_id

    if payload.jenis == "equipment":
        service_id = None
    else:
        if not service_id or not service_id.strip():
            raise HTTPException(status_code=400, detail="Request sparepart repair harus terkait tiket service yang sedang Anda kerjakan")
        svc = await db.service.find_one({"service_id": service_id})
        if not svc:
            raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")

        if svc.get("status") not in ("Proses", "Menunggu_Sparepart"):
            # Sengaja TIDAK mengizinkan tiket "Selesai" lagi — begitu tiket
            # Selesai, biaya sparepart sudah dijumlahkan sekali ke harga_modal
            # unit (lihat update_service) dan tab "Sedang Dipakai" cuma
            # menampilkan tiket berstatus Proses/Menunggu_Sparepart, jadi
            # request yang masuk sesudahnya tidak akan pernah tertagih atau
            # kelihatan lagi di manapun.
            raise HTTPException(
                status_code=400,
                detail=f"Service status {svc.get('status')} tidak bisa request sparepart. Harus Proses atau Menunggu_Sparepart."
            )

        if svc.get("teknisi") != actor:
            raise HTTPException(
                status_code=403,
                detail="Hanya teknisi yang sedang mengerjakan service ini yang boleh request sparepart"
            )

        if svc.get("cabang") != payload.cabang:
            raise HTTPException(status_code=403, detail="Service bukan cabang Anda")

        unit_id = svc.get("unit_id")

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

    unit_doc = None
    if unit_id:
        unit_doc = await db.units.find_one({"unit_id": unit_id})

    doc = {
        "req_id": req_id, "tipe": payload.tipe, "jenis": payload.jenis,
        "service_id": service_id, "unit_id": unit_id,
        "sp_id": payload.sp_id,
        "nama_sp": payload.nama_sp, "jumlah": payload.jumlah,
        "harga_diajukan": payload.harga_diajukan, "alasan": payload.alasan,
        "keterangan": payload.keterangan, "status": "Pending",
        "estimasi_tiba": None, "catatan_kc": "",
        "harga_disetujui": None,
        "product_link": payload.product_link,
        "cabang": payload.cabang, "dibuat_oleh": actor,
        "disetujui_oleh_kc": None, "disetujui_at_kc": None,
        "created_at": now, "updated_at": None,
        # Snapshot fields
        "harga_modal_snapshot": unit_doc.get("harga_modal") if unit_doc else None,
        "unit_nama_snapshot": f"{unit_doc.get('merk')} {unit_doc.get('tipe')}" if unit_doc else None,
    }
    res = await db.request_sparepart.insert_one(doc)
    doc["_id"] = res.inserted_id

    if service_id and payload.jenis == "repair" and svc and svc.get("status") == "Proses":
        await db.service.update_one(
            {"service_id": service_id, "status": "Proses"},
            {"$set": {"status": "Menunggu_Sparepart", "updated_at": now}}
        )

    service_note = f" (Service: {service_id})" if service_id else ""
    await write_log(db, actor, "Request Sparepart", f"{req_id} • {payload.nama_sp} x{payload.jumlah}{service_note}", payload.cabang)
    return _fmt(doc)


async def respond_request(
    db, req_id: str, payload: RequestSparepartResponseRequest,
    actor: str, actor_role: str = '', actor_cabang: str = ''
) -> RequestSparepartResponse:
    """Kepala Cabang review & approve/reject harga yang diajukan teknisi.
    Diterima -> harga_disetujui terkunci, status lanjut ke Menunggu_Pembelian
    (giliran kasir). Ditolak -> Ditolak, dan tiket terkait dibalikin kalau
    tidak ada request lain yang masih menahannya di Menunggu_Sparepart."""
    if payload.status.value == "Ditolak" and not payload.catatan.strip():
        raise HTTPException(status_code=400, detail="Catatan alasan penolakan wajib diisi")

    existing = await db.request_sparepart.find_one({"req_id": req_id})
    if not existing:
        raise HTTPException(404, f"Request {req_id} tidak ditemukan")
    if actor_role == 'kepala_cabang' and existing.get('cabang') != actor_cabang:
        raise HTTPException(status_code=403, detail='Kamu tidak bisa respon request cabang lain')

    now = datetime.now(timezone.utc)
    update = {"updated_at": now, "catatan_kc": payload.catatan}

    if payload.status.value == "Diterima":
        if not payload.harga_disetujui:
            raise HTTPException(status_code=400, detail="Harga disetujui wajib diisi untuk menyetujui request")
        update["status"] = "Menunggu_Pembelian"
        update["harga_disetujui"] = payload.harga_disetujui
        update["disetujui_oleh_kc"] = actor
        update["disetujui_at_kc"] = now
        if payload.estimasi_tiba:
            update["estimasi_tiba"] = payload.estimasi_tiba
    elif payload.status.value == "Ditolak":
        update["status"] = "Ditolak"

    # Atomic claim: filter juga di status "Pending" supaya dua KC (atau dua
    # klik ganda) yang merespon request yang sama tepat bersamaan tidak
    # berdua-duanya "berhasil" menimpa keputusan satu sama lain.
    filt = {"req_id": req_id, "status": "Pending"}
    if actor_role == 'kepala_cabang':
        filt["cabang"] = actor_cabang
    doc = await db.request_sparepart.find_one_and_update(filt, {"$set": update})
    if not doc:
        raise HTTPException(400, "Request sudah direspon")
    updated = await db.request_sparepart.find_one({"req_id": req_id})

    if update.get("status") == "Ditolak":
        await _clear_menunggu_sparepart_if_unblocked(db, doc.get("service_id"))

    await write_log(db, actor, "Respon Request Sparepart", f"{req_id} → {update.get('status', 'updated')}", doc.get("cabang",""))
    return _fmt(updated)


async def beli_request(
    db, req_id: str, payload: RequestSparepartBeliRequest,
    actor: str, actor_role: str = '', actor_cabang: str = ''
) -> RequestSparepartResponse:
    """Kasir catat pembelian: supplier, harga beli aktual (vs harga
    disetujui), bukti/nota. Atomic claim di status Menunggu_Pembelian supaya
    tidak ada dua kasir yang proses request yang sama bersamaan."""
    if actor_role != "kasir":
        raise HTTPException(403, "Hanya Kasir yang bisa mencatat pembelian")
    if payload.barang_di_tangan and not (payload.tanggal_terima and payload.tanggal_terima.strip()):
        raise HTTPException(status_code=400, detail="Tanggal terima wajib diisi kalau barang sudah di tangan")

    now = datetime.now(timezone.utc)
    # Selalu mendarat di Menunggu_Barang dulu di sini, TIDAK langsung ke
    # Diterima meski barang_di_tangan=True — supaya kalau _terima_barang
    # gagal di tengah jalan (mis. gagal buat sparepart master), request-nya
    # nyangkut di status hidup yang masih valid & bisa diulang lewat
    # /terima, bukan diam-diam "Diterima" padahal efek inventorinya belum
    # kejadian.
    doc = await db.request_sparepart.find_one_and_update(
        {"req_id": req_id, "status": "Menunggu_Pembelian", "cabang": actor_cabang},
        {"$set": {
            "status": "Menunggu_Barang",
            "supplier": payload.supplier,
            "harga_beli_aktual": payload.harga_beli_aktual,
            "bukti_url": payload.bukti_url,
            "catatan_beli": payload.catatan,
            "dibeli_oleh": actor,
            "dibeli_at": now,
            "updated_at": now,
        }},
        return_document=True,
    )
    if not doc:
        raise HTTPException(409, "Request tidak dalam status Menunggu_Pembelian atau sudah diproses")

    await write_log(
        db, actor, "Catat Pembelian Sparepart",
        f"{req_id} • {doc['nama_sp']} x{doc['jumlah']} dari {payload.supplier} @ Rp{payload.harga_beli_aktual:,}",
        doc.get("cabang", "")
    )

    if payload.barang_di_tangan:
        return await _claim_and_terima_barang(db, req_id, actor_cabang, tanggal_terima=payload.tanggal_terima, actor=actor)

    return _fmt(doc)


async def terima_request(
    db, req_id: str, payload: RequestSparepartTerimaRequest,
    actor: str, actor_role: str = '', actor_cabang: str = ''
) -> RequestSparepartResponse:
    """Kasir konfirmasi barang fisik sudah sampai -> masuk inventory
    (Barang Diterima & Masuk Inventory)."""
    if actor_role != "kasir":
        raise HTTPException(403, "Hanya Kasir yang bisa konfirmasi barang diterima")

    if payload.catatan:
        doc = await db.request_sparepart.find_one({"req_id": req_id, "status": "Menunggu_Barang", "cabang": actor_cabang})
        if doc:
            await db.request_sparepart.update_one(
                {"req_id": req_id},
                {"$set": {"catatan_kc": (doc.get("catatan_kc") or "") + " | " + payload.catatan}}
            )

    return await _claim_and_terima_barang(db, req_id, actor_cabang, tanggal_terima=payload.tanggal_terima, actor=actor)


async def _claim_and_terima_barang(db, req_id: str, actor_cabang: str, tanggal_terima: Optional[str], actor: str) -> RequestSparepartResponse:
    """Klaim atomik dari Menunggu_Barang -> processing_terima, lalu jalankan
    efek inventory. Kalau efeknya gagal di tengah jalan, status DIKEMBALIKAN
    ke Menunggu_Barang (bukan nyangkut permanen di status transient yang
    tidak ada di enum resmi) supaya kasir bisa coba ulang."""
    doc = await db.request_sparepart.find_one_and_update(
        {"req_id": req_id, "status": "Menunggu_Barang", "cabang": actor_cabang},
        {"$set": {"status": "processing_terima", "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )
    if not doc:
        raise HTTPException(409, "Request tidak dalam status Menunggu_Barang atau sudah diproses")

    try:
        return await _terima_barang(db, doc, tanggal_terima=tanggal_terima, actor=actor)
    except Exception:
        await db.request_sparepart.update_one(
            {"req_id": req_id, "status": "processing_terima"},
            {"$set": {"status": "Menunggu_Barang", "updated_at": datetime.now(timezone.utc)}}
        )
        raise


async def _terima_barang(db, doc: dict, tanggal_terima: Optional[str], actor: str) -> RequestSparepartResponse:
    """Barang diterima & masuk inventory. Kalau request terkait tiket service
    (jenis repair, service_id ada), langsung auto-reserved ke tiket itu
    ('Sedang Dipakai') — tidak lewat pool 'Tersedia' umum dulu, sesuai
    keputusan bisnis: reservasi otomatis. Kalau tidak terkait tiket (restock
    umum / equipment), masuk stok umum sparepart."""
    from app.services.sparepart import create_sparepart
    from app.schemas.sparepart import SparepartCreateRequest

    req_id = doc["req_id"]
    now = datetime.now(timezone.utc)
    cabang = doc.get("cabang", "")
    service_id = doc.get("service_id")
    jenis = doc.get("jenis") or "repair"
    harga_beli_aktual = doc.get("harga_beli_aktual", 0)
    jumlah = doc.get("jumlah", 1)
    auto_reserve = bool(service_id) and jenis == "repair"

    sp_id = doc.get("sp_id")
    if sp_id:
        existing_sp = await db.sparepart.find_one({"sp_id": sp_id, "cabang": cabang})
    else:
        existing_sp = None

    if existing_sp:
        # Sparepart sudah ada di master data: update harga_beli aktual, dan
        # tambah stok HANYA kalau tidak langsung direservasi ke tiket.
        set_fields = {"harga_beli": harga_beli_aktual, "updated_at": now}
        if not auto_reserve:
            await db.sparepart.update_one(
                {"sp_id": sp_id, "cabang": cabang},
                {"$inc": {"stok": jumlah}, "$set": set_fields}
            )
        else:
            await db.sparepart.update_one({"sp_id": sp_id, "cabang": cabang}, {"$set": set_fields})
    else:
        # Sparepart baru: buat master data. Stok = 0 kalau langsung
        # direservasi ke tiket (tidak masuk pool umum), atau = jumlah kalau
        # restock/equipment biasa.
        new_sp = await create_sparepart(db, SparepartCreateRequest(
            nama=doc["nama_sp"], kategori="Sparepart", jenis=jenis, satuan="pcs",
            stok=0 if auto_reserve else jumlah,
            harga_beli=harga_beli_aktual, harga_jual=0,
            cabang=cabang, catatan=f"Auto-created from request {req_id}",
            product_link=doc.get("product_link"),
        ), actor=actor)
        sp_id = new_sp.sp_id
        await db.request_sparepart.update_one({"req_id": req_id}, {"$set": {"sp_id": sp_id}})

    final_update = {
        "diterima_oleh": actor, "diterima_at": now,
        "tanggal_terima": tanggal_terima or fmt_waktu_date(now),
        "updated_at": now,
    }

    if auto_reserve:
        svc = await db.service.find_one({"service_id": service_id})
        if svc:
            items = svc.get("sparepart_items", [])
            existing_item = next((i for i in items if i["sp_id"] == sp_id), None)
            if existing_item:
                existing_item["jumlah"] += jumlah
            else:
                items.append({
                    "sp_id": sp_id, "nama": doc["nama_sp"], "jumlah": jumlah,
                    "harga_modal": harga_beli_aktual, "mulai_pakai": now,
                })
            await db.service.update_one(
                {"service_id": service_id},
                {"$set": {"sparepart_items": items, "updated_at": now}}
            )
        final_update["status"] = "Digunakan"
    else:
        final_update["status"] = "Diterima"

    await db.request_sparepart.update_one({"req_id": req_id}, {"$set": final_update})
    updated = await db.request_sparepart.find_one({"req_id": req_id})

    if auto_reserve:
        await _clear_menunggu_sparepart_if_unblocked(db, service_id)

    await write_log(
        db, actor, "Barang Diterima - Sparepart",
        f"{req_id} • {doc['nama_sp']} x{jumlah}" + (f" → auto-reserved ke {service_id}" if auto_reserve else " → stok umum"),
        cabang
    )
    return _fmt(updated)


def fmt_waktu_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


async def get_request_detail(db, req_id: str) -> RequestSparepartResponse:
    """Get detail request sparepart by req_id"""
    doc = await db.request_sparepart.find_one({"req_id": req_id})
    if not doc:
        raise HTTPException(404, f"Request {req_id} tidak ditemukan")
    return _fmt(doc)
