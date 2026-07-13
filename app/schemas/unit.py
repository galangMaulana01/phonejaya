from pydantic import BaseModel, field_validator
from typing import Optional, List
from enum import Enum
from datetime import datetime
import re


class SparepartItem(BaseModel):
    sp_id:  str
    jumlah: int = 1


class StatusEnum(str, Enum):
    tersedia = "Tersedia"
    sold     = "Sold"
    booking  = "Booking"
    service  = "Service"


class KondisiHP(str, Enum):
    mulus  = "Mulus"
    repair = "Repair"


class UnitCreateRequest(BaseModel):
    kat_kode:      str
    kondisi_kode:  str
    kondisi_hp:    KondisiHP
    merk:          str
    tipe:          str
    storage:       str = "-"
    ram:           str = "-"
    warna:         str = "-"
    imei:          str = "-"       # IMEI 1 (wajib diisi di frontend)
    imei2:         str = "-"       # IMEI 2 opsional
    tipe_sim:      str = "Single SIM"   # Single SIM / Dual SIM / eSIM / WiFi Only
    keamanan:      str = "Tidak Ada"    # Face ID / Fingerprint / Touch ID / Tidak Ada
    speaker:       str = "Normal"       # Normal / Tidak Normal
    lcd:           str = "Original"     # Original / Tidak Original
    battery:       int = 100
    battery_health: int = 0            # Battery Health % (opsional, 0 = tidak diisi)
    harga_modal:   int = 0
    harga_jual:    int = 0
    garansi_toko:  int = 7             # hari
    catatan:       str = ""
    cabang:        str = "JYP"
    keluhan:       str = ""
    sparepart_items: List[SparepartItem] = []
    foto_url:       Optional[str] = None

    @field_validator("merk", "tipe")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        return v.strip()
    @field_validator("imei")
    @classmethod
    def imei_format(cls, v: str) -> str:
        if v and v != "-" and not re.match(r'^\d{14,16}$', v):
            raise ValueError("IMEI harus 14-16 digit angka")
        return v



class ApproveRepairRequest(BaseModel):
    harga_jual: int

    @field_validator("harga_jual")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Harga jual harus lebih dari 0")
        return v


class UnitResponse(BaseModel):
    id:            str
    unit_id:       str
    merk:          str
    tipe:          str
    storage:       str
    ram:           str
    warna:         str
    imei:          str
    imei2:         str = "-"
    tipe_sim:      str = "Single SIM"
    keamanan:      str = "Tidak Ada"
    speaker:       str = "Normal"
    lcd:           str = "Original"
    harga_modal:   int
    harga_jual:    int
    kondisi:       str
    kondisi_hp:    str
    battery:       int
    battery_health: int = 0
    status:        str
    kategori:      str
    catatan:       str
    cabang:        str
    locked:        bool
    garansi_toko:  int = 7
    input_oleh:    str = ""
    tgl_masuk:     str = ""
    tgl_terjual:   Optional[str] = None
    service_id:    Optional[str] = None
    created_by:    str = ""
    foto_url:       Optional[str] = None
