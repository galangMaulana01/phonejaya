from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum


class StatusEnum(str, Enum):
    tersedia = "Tersedia"
    sold     = "Sold"
    booking  = "Booking"
    service  = "Service"


class UnitCreateRequest(BaseModel):
    kat_kode:     str
    kondisi_kode: str
    merk:         str
    tipe:         str
    storage:      str = "-"
    warna:        str = "-"
    imei:         str = "-"
    harga_modal:  int = 0
    harga_jual:   int = 0
    battery:      int = 100
    catatan:      str = ""
    cabang:       str = "JYP"

    @field_validator("merk", "tipe")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        return v.strip()


class UnitUpdateRequest(BaseModel):
    harga_modal: Optional[int] = None
    harga_jual:  Optional[int] = None
    battery:     Optional[int] = None
    status:      Optional[StatusEnum] = None
    catatan:     Optional[str] = None


class UnitResponse(BaseModel):
    id: str
    unit_id: str
    merk: str
    tipe: str
    storage: str
    warna: str
    imei: str
    harga_modal: int
    harga_jual: int
    kondisi: str
    battery: int
    status: str
    kategori: str
    catatan: str
    cabang: str
