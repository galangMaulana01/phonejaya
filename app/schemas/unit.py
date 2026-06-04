from pydantic import BaseModel, field_validator
from typing import Optional, List


class SparepartItem(BaseModel):
    sp_id:  str
    jumlah: int = 1
from enum import Enum


class StatusEnum(str, Enum):
    tersedia = "Tersedia"
    sold     = "Sold"
    booking  = "Booking"
    service  = "Service"


class KondisiHP(str, Enum):
    """Kondisi HP saat masuk dari penjual."""
    mulus  = "Mulus"    # langsung ke stok jual
    repair = "Repair"   # masuk antrian teknisi dulu


class UnitCreateRequest(BaseModel):
    """
    Input HP baru dari penjual (kasir / owner).
    Setelah diposting → LOCKED, tidak bisa diedit siapapun.
    """
    kat_kode:      str
    kondisi_kode:  str           # BN / MN / EX / RJ (kode fisik)
    kondisi_hp:    KondisiHP     # Mulus → stok | Repair → service
    merk:          str
    tipe:          str
    storage:       str = "-"
    ram:           str = "-"
    warna:         str = "-"
    imei:          str = "-"
    harga_modal:   int = 0
    battery:       int = 100
    catatan:       str = ""
    cabang:        str = "JYP"

    # Kalau Mulus langsung set harga jual
    harga_jual:    int = 0

    # Kalau Repair → harga jual diisi oleh kasir/owner saat approval
    keluhan:       str = ""      # wajib diisi kalau Repair

    @field_validator("merk", "tipe")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        return v.strip()


class ApproveRepairRequest(BaseModel):
    """
    Kasir / Owner menetapkan harga jual setelah teknisi selesai repair.
    Unit akan pindah ke stok Tersedia.
    """
    harga_jual: int

    @field_validator("harga_jual")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Harga jual harus lebih dari 0")
        return v


class UnitResponse(BaseModel):
    id:          str
    unit_id:     str
    merk:        str
    tipe:        str
    storage:     str
    ram:         str
    warna:       str
    imei:        str
    harga_modal: int
    harga_jual:  int
    kondisi:     str
    kondisi_hp:  str
    battery:     int
    status:      str
    kategori:    str
    catatan:     str
    cabang:      str
    locked:      bool   # True = tidak bisa diedit
    service_id:  Optional[str] = None   # diisi kalau unit sedang / pernah di-repair
