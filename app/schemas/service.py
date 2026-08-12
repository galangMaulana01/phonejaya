from pydantic import BaseModel, field_validator
from typing import Optional, List
from enum import Enum


class StatusServiceEnum(str, Enum):
    antrian             = "Antrian"             # baru masuk dari kasir, belum diambil teknisi
    proses              = "Proses"              # teknisi sedang kerjakan
    menunggu_sparepart  = "Menunggu_Sparepart"   # teknisi lagi nunggu sparepart yang direquest tiba
    selesai             = "Selesai"              # teknisi selesai, menunggu approval harga
    approved            = "Approved"             # kasir/owner sudah set harga → unit ke stok
    ditolak             = "Ditolak"              # unit tidak bisa diperbaiki


class ServiceCreateRequest(BaseModel):
    """
    Dibuat otomatis saat kasir input HP dengan kondisi_hp = Repair.
    Tidak perlu diinput manual oleh teknisi.
    """
    unit_id:          str
    nama_customer:    str = ""   # opsional untuk HP second dari penjual
    kontak_customer:  str = ""
    keluhan:          str
    catatan_kerusakan: str = ""
    cabang:           str = "JYP"

    @field_validator("keluhan")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Keluhan tidak boleh kosong")
        return v.strip()


class ServiceUseSparepartRequest(BaseModel):
    """Teknisi pakai sparepart yang SUDAH ADA di stok cabang untuk servis
    ini secara langsung — beda dari request_sparepart (yang lewat approval
    kepala_cabang -> kasir untuk part yang belum/tidak ada di stok)."""
    sp_id:  str
    jumlah: int = 1

    @field_validator("jumlah")
    @classmethod
    def jumlah_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Jumlah harus lebih dari 0")
        return v


class ServiceUpdateRequest(BaseModel):
    """
    Hanya teknisi yang bisa update status & catatan.
    Teknisi TIDAK bisa approve (set harga jual).
    """
    status:            Optional[StatusServiceEnum] = None
    catatan_kerusakan: Optional[str] = None
    teknisi:           Optional[str] = None
    estimasi_selesai:  Optional[str] = None
    foto_before_urls:  Optional[List[str]] = None
    foto_after_urls:   Optional[List[str]] = None
    link_shopee:       Optional[str] = None  # Shopee product link for reference


class ServiceResponse(BaseModel):
    id:               str
    service_id:       str
    unit_id:          str
    unit_label:       str
    nama_customer:    str
    kontak_customer:  str
    keluhan:          str
    catatan_kerusakan: str
    status:           str
    teknisi:          str
    foto_urls:        List[str]
    cabang:           str
    estimasi_selesai: Optional[str] = None
    created_at:       str
    updated_at:       Optional[str] = None
    foto_before_urls: List[str] = []
    foto_after_urls:  List[str] = []
    sparepart_items:  List[dict] = []
    # Diisi sekali saat tiket pindah ke Selesai (kalau ada sparepart_items) —
    # dasar window "Riwayat Pemakaian" (lihat sparepart.list_sparepart_riwayat).
    sparepart_selesai_at: Optional[str] = None
