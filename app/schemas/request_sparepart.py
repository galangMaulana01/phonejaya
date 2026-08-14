from pydantic import BaseModel, field_validator
from typing import Optional, Literal
from enum import Enum


# Alur baru (lihat diagram "WORKFLOW SERVICE & REQUEST SPAREPART"):
# Pending -> [KC approve harga] -> Menunggu_Pembelian (audit: harga_disetujui
#   terkunci di titik ini, tercatat sbg "Disetujui" lewat disetujui_at_kc)
# -> [Kasir catat pembelian] -> Menunggu_Barang (audit: "Dibeli" tercatat
#   lewat dibeli_at) — atau langsung Diterima kalau barang_di_tangan=True
# -> [Kasir konfirmasi barang sampai] -> Diterima -> stok masuk inventory.
#   Kalau request terkait service_id (jenis repair), part itu DITAHAN untuk
#   tiket itu (tidak masuk pool "Tersedia" umum) tapi BELUM ditulis ke
#   sparepart_items tiket — status tiket masih Menunggu_Sparepart, badge FE
#   "Sparepart Tersedia" dihitung dari status Diterima ini. Baru saat teknisi
#   eksplisit klik "Gunakan Sparepart" (request_sparepart_service.
#   confirm_use_request) part itu ditulis ke tiket & status jadi Digunakan.
# Ditolak bisa terjadi di titik KC review.
class StatusRequestEnum(str, Enum):
    pending             = "Pending"
    disetujui           = "Disetujui"            # transient/audit-only
    menunggu_pembelian  = "Menunggu_Pembelian"
    dibeli              = "Dibeli"                # transient/audit-only
    menunggu_barang     = "Menunggu_Barang"
    diterima            = "Diterima"
    digunakan           = "Digunakan"
    ditolak             = "Ditolak"


# Jenis sparepart yang bisa diminta lewat pipeline pengadaan teknisi —
# "dijual" tidak lewat sini, itu diinput owner/KC langsung di halaman Sparepart.
REQUEST_JENIS = {"repair", "equipment"}

# Enum for KC response input (they send Diterima/Ditolak)
class KCResponseStatusEnum(str, Enum):
    diterima = "Diterima"
    ditolak  = "Ditolak"


class RequestSparepartCreateRequest(BaseModel):
    tipe:           str
    jenis:          str = "repair"     # repair (terkait tiket) | equipment (alat, tidak terkait tiket)
    service_id:     Optional[str] = None  # WAJIB untuk jenis=repair, diabaikan untuk jenis=equipment
    sp_id:          Optional[str] = None
    nama_sp:        str
    jumlah:         int = 1
    # Opsional saat dibuat — teknisi cuma perlu bilang butuh apa & kenapa.
    # Kepala Cabang/Kasir yang mengisi harga & link produk belakangan kalau
    # masih kosong, supaya teknisi tidak dipaksa tahu harga pasar sparepart
    # selagi masih megang HP yang rusak.
    harga_diajukan: Optional[int] = None
    alasan:         str
    keterangan:     str = ""
    cabang:         str = "JYP"
    product_link:   Optional[str] = None

    @field_validator("jenis")
    @classmethod
    def jenis_valid(cls, v: str) -> str:
        if v not in REQUEST_JENIS:
            raise ValueError(f"Jenis harus salah satu dari: {', '.join(sorted(REQUEST_JENIS))}")
        return v

    @field_validator("nama_sp")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip(): raise ValueError("Nama tidak boleh kosong")
        return v.strip()

    @field_validator("alasan")
    @classmethod
    def alasan_not_empty(cls, v: str) -> str:
        if not v.strip(): raise ValueError("Alasan wajib diisi")
        return v.strip()

    @field_validator("jumlah")
    @classmethod
    def jumlah_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Jumlah harus lebih dari 0")
        return v

    @field_validator("harga_diajukan")
    @classmethod
    def harga_diajukan_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("Harga diajukan harus lebih dari 0")
        return v

    @field_validator("product_link")
    @classmethod
    def validate_product_link(cls, v: Optional[str]) -> Optional[str]:
        # Tidak wajib lagi di sini walau sp_id kosong — Kasir masih bisa isi
        # link produk belakangan pas mencatat pembelian. Kalau diisi, tetap
        # harus HTTPS.
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("Link produk harus menggunakan HTTPS")
        return v


class RequestSparepartResponseRequest(BaseModel):
    """Kepala Cabang review & approve/reject harga yang diajukan teknisi."""
    status:           KCResponseStatusEnum
    harga_disetujui:  Optional[int] = None   # WAJIB kalau status Diterima; terkunci setelah ini
    estimasi_tiba:    Optional[str] = None
    catatan:          str = ""

    @field_validator("harga_disetujui")
    @classmethod
    def harga_disetujui_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("Harga disetujui harus lebih dari 0")
        return v


class RequestSparepartBeliRequest(BaseModel):
    """Kasir mencatat pembelian: supplier, harga beli aktual (dibanding harga
    disetujui), dan bukti/nota. Kalau barang_di_tangan=True (misal beli COD di
    toko terdekat), langsung lanjut ke Diterima+masuk inventory di request yang
    sama — kalau tidak, request masuk resting-state Menunggu_Barang dulu."""
    supplier:          str
    harga_beli_aktual: int
    bukti_url:         Optional[str] = None
    catatan:           str = ""
    barang_di_tangan:  bool = False
    tanggal_terima:    Optional[str] = None   # hanya dipakai kalau barang_di_tangan=True

    @field_validator("supplier")
    @classmethod
    def supplier_not_empty(cls, v: str) -> str:
        if not v.strip(): raise ValueError("Supplier wajib diisi")
        return v.strip()

    @field_validator("harga_beli_aktual")
    @classmethod
    def harga_beli_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Harga beli aktual harus lebih dari 0")
        return v


class RequestSparepartGunakanRequest(BaseModel):
    """Teknisi konfirmasi 'Gunakan Sparepart'. estimasi_selesai cuma wajib
    (dicek di service layer, bukan di sini) kalau ini request blocking
    terakhir buat tiketnya — dibiarkan Optional di sini supaya konfirmasi
    yang tidak langsung melepas tiket (masih ada request lain yang menahan)
    tidak dipaksa mengisi estimasi yang belum relevan."""
    estimasi_selesai: Optional[str] = None


class RequestSparepartTerimaRequest(BaseModel):
    """Kasir konfirmasi barang fisik sudah sampai/di tangan -> masuk inventory."""
    tanggal_terima: Optional[str] = None
    catatan:        str = ""


class RequestSparepartResponse(BaseModel):
    id:               str
    req_id:           str
    tipe:             str
    jenis:            str = "repair"
    service_id:       Optional[str] = None
    unit_id:          Optional[str] = None
    sp_id:            Optional[str] = None
    nama_sp:          str
    jumlah:           int
    harga_diajukan:   Optional[int] = None
    alasan:           str = ""
    keterangan:       str
    status:           str
    estimasi_tiba:    Optional[str] = None
    catatan_kc:       str = ""
    harga_disetujui:  Optional[int] = None
    supplier:          Optional[str] = None
    harga_beli_aktual: Optional[int] = None
    bukti_url:         Optional[str] = None
    catatan_beli:      Optional[str] = None
    dibeli_oleh:       Optional[str] = None
    dibeli_at:         Optional[str] = None
    tanggal_terima:    Optional[str] = None
    diterima_oleh:     Optional[str] = None
    diterima_at:       Optional[str] = None
    product_link:     Optional[str] = None
    cabang:           str
    dibuat_oleh:      str
    disetujui_oleh_kc: Optional[str] = None
    disetujui_at_kc:   Optional[str] = None
    created_at:       str
    updated_at:       Optional[str] = None
    # Snapshot fields for legacy/history consistency
    harga_modal_snapshot: Optional[int] = None
    unit_nama_snapshot:   Optional[str] = None
    # Legacy fields (flow lama, dipertahankan supaya data historis tetap terbaca)
    harga_jual:       Optional[int] = None
    approved_by:      Optional[str] = None
    approved_at:      Optional[str] = None


class RequestSparepartNotifItem(BaseModel):
    """Ringkasan buat notifikasi teknisi: 'sparepart yang Anda minta sudah
    diterima/direservasi'. Cuma field yang dibutuhkan bell notifikasi."""
    req_id:      str
    nama_sp:     str
    jumlah:      int
    service_id:  Optional[str] = None
    unit_label:  Optional[str] = None
