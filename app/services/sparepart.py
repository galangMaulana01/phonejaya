from datetime import datetime, timedelta, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.sparepart import (
    SparepartCreateRequest, SparepartUpdateStokRequest, SparepartResponse,
    SparepartInUseItem, DEFAULT_SPAREPART_JENIS,
)
from app.services.log_service import write_log
from app.utils.formatters import fmt_waktu

# Berapa lama sebuah tiket yang baru Selesai masih tampil di "Riwayat
# Pemakaian" sebelum menghilang dari view itu (datanya sendiri tidak
# terhapus — cuma tidak lagi ikut ke-query di sini setelah lewat jendela
# ini). Dipakai juga oleh notifikasi teknisi (request_sparepart_service)
# supaya jendela "baru selesai" konsisten di seluruh app.
RIWAYAT_WINDOW_HOURS = 2


def _fmt(doc: dict, dipakai: int = 0) -> SparepartResponse:
    p = doc.get("dimensi_p")
    l = doc.get("dimensi_l")
    t = doc.get("dimensi_t")
    dim_str = f"{p} x {l} x {t} cm" if p and l and t else ""
    return SparepartResponse(
        id          = str(doc["_id"]),
        sp_id       = doc.get("sp_id", str(doc["_id"])),
        nama        = doc.get("nama", ""),
        kategori    = doc.get("kategori", "Umum"),
        jenis       = doc.get("jenis") or DEFAULT_SPAREPART_JENIS,
        satuan      = doc.get("satuan", "pcs"),
        stok        = doc.get("stok", 0),
        dipakai     = dipakai,
        harga_beli  = doc.get("harga_beli", 0),
        harga_jual  = doc.get("harga_jual", 0),
        dimensi_p   = p,
        dimensi_l   = l,
        dimensi_t   = t,
        catatan     = doc.get("catatan", ""),
        cabang      = doc.get("cabang", ""),
        dimensi_str = dim_str,
    )


async def _dipakai_by_sp_id(db: AsyncIOMotorDatabase, cabang: Optional[str] = None) -> dict:
    """Total sparepart_items.jumlah per sp_id, dijumlahkan lintas semua tiket
    servis yang masih Proses/Menunggu_Sparepart — dipakai teknisi tapi belum
    kelar. `stok` di dokumen sparepart HANYA merepresentasikan sisa yang
    bebas (sudah dipotong atomik sejak dipakai); tanpa ini, satu-satunya cara
    melihat berapa yang sedang dipakai adalah menjumlah manual satu-satu di
    tab "Sedang Dipakai". Dihitung di Python (bukan aggregation pipeline)
    supaya konsisten dengan list_sparepart_in_use dan tidak tergantung
    dukungan $unwind/$group di mongomock (dev lokal)."""
    query: dict = {"status": {"$in": ["Proses", "Menunggu_Sparepart"]}, "sparepart_items": {"$ne": []}}
    if cabang:
        query["cabang"] = cabang
    tickets = await db.service.find(query).to_list(length=None)
    totals: dict = {}
    for ticket in tickets:
        for item in ticket.get("sparepart_items") or []:
            totals[item["sp_id"]] = totals.get(item["sp_id"], 0) + item["jumlah"]
    return totals


async def _next_sp_id(db: AsyncIOMotorDatabase) -> str:
    result = await db.counters.find_one_and_update(
        {"_id": "SP"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return f"SP-{str(result['seq']).zfill(3)}"


async def list_sparepart(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
    kategori: Optional[str] = None,
    jenis: Optional[str] = None,
) -> List[SparepartResponse]:
    # Excludes sparepart docs reserved for one specific service ticket
    # (auto-created by request_sparepart_service._terima_barang with stok=0
    # when a repair request is tied to a ticket) — those were never real
    # browsable stock, just an internal placeholder until the teknisi
    # confirms use, so they shouldn't clutter "Tersedia". `None` matches
    # both "field absent" (every normal sparepart) and "explicitly null".
    query: dict = {"reserved_for_service_id": None}
    if cabang:   query["cabang"]   = cabang
    if kategori: query["kategori"] = kategori
    if jenis:
        # Sparepart created before the `jenis` field existed have no such
        # key stored at all (not even the default) — treat a missing key as
        # "repair" so old stock isn't invisible in every jenis-filtered tab.
        query["jenis"] = jenis if jenis != DEFAULT_SPAREPART_JENIS else {"$in": [DEFAULT_SPAREPART_JENIS, None]}
    docs = await db.sparepart.find(query).sort("nama", 1).to_list(length=None)
    dipakai_map = await _dipakai_by_sp_id(db, cabang)
    return [_fmt(d, dipakai=dipakai_map.get(d.get("sp_id", ""), 0)) for d in docs]


async def create_sparepart(
    db: AsyncIOMotorDatabase,
    payload: SparepartCreateRequest,
    actor: str,
    # Set only by request_sparepart_service._terima_barang for a repair
    # request tied to one specific ticket — marks this doc as an internal
    # placeholder (stok=0) rather than real browsable stock, so list_sparepart
    # excludes it from "Tersedia". Never set from the public POST /sparepart route.
    reserved_for_service_id: Optional[str] = None,
) -> SparepartResponse:
    sp_id = await _next_sp_id(db)
    now   = datetime.now(timezone.utc)
    doc   = {
        "sp_id":      sp_id,
        "nama":       payload.nama,
        "kategori":   payload.kategori,
        "jenis":      payload.jenis,
        "satuan":     payload.satuan,
        "stok":       payload.stok,
        "harga_beli": payload.harga_beli,
        "harga_jual": payload.harga_jual,
        "dimensi_p":  payload.dimensi_p,
        "dimensi_l":  payload.dimensi_l,
        "dimensi_t":  payload.dimensi_t,
        "catatan":    payload.catatan,
        "cabang":     payload.cabang,
        "created_at": now,
        "created_by": actor,
        "updated_at": None,
        "reserved_for_service_id": reserved_for_service_id,
    }
    result = await db.sparepart.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, actor, "Tambah Sparepart", f"{sp_id} • {payload.nama} stok:{payload.stok}", payload.cabang)
    return _fmt(doc)


async def update_stok(
    db: AsyncIOMotorDatabase,
    sp_id: str,
    payload: SparepartUpdateStokRequest,
    actor: str,
    user_role: str = '',
    user_cabang: str = '',
) -> SparepartResponse:
    sp = await db.sparepart.find_one({"sp_id": sp_id})
    if not sp:
        raise HTTPException(status_code=404, detail=f"Sparepart {sp_id} tidak ditemukan")
    if user_role == 'kepala_cabang' and sp.get('cabang') != user_cabang:
        raise HTTPException(status_code=403, detail='Sparepart bukan milik cabangmu')

    now = datetime.now(timezone.utc)
    if payload.delta < 0:
        # Atomic decrement with stok check
        result = await db.sparepart.find_one_and_update(
            {"sp_id": sp_id, "stok": {"$gte": abs(payload.delta)}},
            {"$inc": {"stok": payload.delta}, "$set": {"updated_at": now}},
            return_document=False,
        )
        if not result:
            raise HTTPException(status_code=400, detail=f"Stok tidak cukup. Stok saat ini: {sp['stok']}")
    else:
        # Atomic increment
        await db.sparepart.find_one_and_update(
            {"sp_id": sp_id},
            {"$inc": {"stok": payload.delta}, "$set": {"updated_at": now}},
            return_document=False,
        )
    
    updated = await db.sparepart.find_one({"sp_id": sp_id})
    aksi = "tambah" if payload.delta > 0 else "kurangi"
    await write_log(db, actor, "Update Stok Sparepart",
        f"{sp_id} • {sp['nama']} {aksi} {abs(payload.delta)} → stok:{updated['stok']}", sp.get("cabang",""))
    return _fmt(updated)


async def list_sparepart_in_use(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
) -> List[SparepartInUseItem]:
    """Sparepart 'Sedang Dipakai' — satu baris per sparepart_items entry di
    setiap tiket servis yang masih Proses ATAU Menunggu_Sparepart, dilengkapi
    info tiket/unit/teknisi. Menunggu_Sparepart perlu diikutkan juga: kalau
    satu tiket punya >1 request sparepart dan salah satunya sudah diterima
    (auto-reserved ke sparepart_items) sementara request lain masih belum
    selesai, tiketnya tetap Menunggu_Sparepart sampai SEMUA request repair-nya
    kelar — part yang sudah diterima itu tidak boleh jadi tak terlihat cuma
    karena tiketnya belum sepenuhnya lepas dari status menunggu.
    Tidak menyentuh koleksi sparepart sama sekali (stoknya sudah dipotong
    langsung saat use_sparepart, bukan di sini) — ini murni tampilan agregasi."""
    query: dict = {"status": {"$in": ["Proses", "Menunggu_Sparepart"]}, "sparepart_items": {"$ne": []}}
    if cabang:
        query["cabang"] = cabang
    tickets = await db.service.find(query).to_list(length=None)

    result: List[SparepartInUseItem] = []
    for ticket in tickets:
        items = ticket.get("sparepart_items") or []
        if not items:
            continue
        unit = await db.units.find_one({"unit_id": ticket.get("unit_id", "")}) if ticket.get("unit_id") else None
        for item in items:
            sp = await db.sparepart.find_one({"sp_id": item["sp_id"]})
            mulai = item.get("mulai_pakai")
            result.append(SparepartInUseItem(
                sp_id=item["sp_id"],
                nama=item.get("nama", ""),
                kategori=sp.get("kategori", "") if sp else "",
                harga_modal=item.get("harga_modal", item.get("harga_jual", 0)),
                jumlah=item["jumlah"],
                service_id=ticket.get("service_id", ""),
                unit_label=ticket.get("unit_label", ""),
                imei=unit.get("imei", "") if unit else "",
                teknisi=ticket.get("teknisi", ""),
                mulai_pakai=fmt_waktu(mulai) if isinstance(mulai, datetime) else mulai,
                cabang=ticket.get("cabang", ""),
            ))
    return result


async def list_sparepart_riwayat(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
) -> List[SparepartInUseItem]:
    """Sparepart 'Riwayat Pemakaian' — sparepart_items dari tiket yang BARU
    Selesai (dalam RIWAYAT_WINDOW_HOURS terakhir), dengan badge "Selesai
    Dipakai". Ini TRANSIEN sengaja: begitu lewat jendela waktu, baris ini
    berhenti muncul di sini walau datanya tetap utuh di dokumen service —
    bukan arsip permanen, cuma penanda "baru saja selesai dipakai"."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RIWAYAT_WINDOW_HOURS)
    query: dict = {"sparepart_selesai_at": {"$gte": cutoff}, "sparepart_items": {"$ne": []}}
    if cabang:
        query["cabang"] = cabang
    tickets = await db.service.find(query).to_list(length=None)

    result: List[SparepartInUseItem] = []
    for ticket in tickets:
        items = ticket.get("sparepart_items") or []
        if not items:
            continue
        unit = await db.units.find_one({"unit_id": ticket.get("unit_id", "")}) if ticket.get("unit_id") else None
        selesai = ticket.get("sparepart_selesai_at")
        selesai_fmt = fmt_waktu(selesai) if isinstance(selesai, datetime) else selesai
        for item in items:
            sp = await db.sparepart.find_one({"sp_id": item["sp_id"]})
            mulai = item.get("mulai_pakai")
            result.append(SparepartInUseItem(
                sp_id=item["sp_id"],
                nama=item.get("nama", ""),
                kategori=sp.get("kategori", "") if sp else "",
                harga_modal=item.get("harga_modal", item.get("harga_jual", 0)),
                jumlah=item["jumlah"],
                service_id=ticket.get("service_id", ""),
                unit_label=ticket.get("unit_label", ""),
                imei=unit.get("imei", "") if unit else "",
                teknisi=ticket.get("teknisi", ""),
                mulai_pakai=fmt_waktu(mulai) if isinstance(mulai, datetime) else mulai,
                selesai_pakai=selesai_fmt,
                cabang=ticket.get("cabang", ""),
            ))
    return result
