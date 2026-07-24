from pydantic import BaseModel, field_validator
from typing import Optional, Literal
from enum import Enum


class StatusRequestEnum(str, Enum):
    pending        = "Pending"
    menunggu_kasir = "Menunggu_Kasir"
    selesai        = "Selesai"
    ditolak        = "Ditolak"

# Enum for KC response input (they send Diterima/Ditolak)
class KCResponseStatusEnum(str, Enum):
    diterima = "Diterima"
    ditolak  = "Ditolak"


class RequestSparepartCreateRequest(BaseModel):
    tipe:       str
    sp_id:      Optional[str] = None
    nama_sp:    str
    jumlah:     int = 1
    keterangan: str = ""
    cabang:     str = "JYP"
    product_link: Optional[str] = None

    @field_validator("nama_sp")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip(): raise ValueError("Nama tidak boleh kosong")
        return v.strip()


class RequestSparepartResponseRequest(BaseModel):
    status:         KCResponseStatusEnum
    estimasi_tiba:  Optional[str] = None
    catatan:        str = ""


class RequestSparepartApproveRequest(BaseModel):
    """Kasir approval akhir - set harga jual dan approve/reject."""
    harga_jual: int
    status:     Literal["Selesai", "Ditolak"]
    catatan:    str = ""

    @field_validator("harga_jual")
    @classmethod
    def harga_jual_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Harga jual harus lebih dari 0")
        return v


class RequestSparepartResponse(BaseModel):
    id:               str
    req_id:           str
    tipe:             str
    sp_id:            Optional[str] = None
    nama_sp:          str
    jumlah:           int
    keterangan:       str
    status:           str
    estimasi_tiba:    Optional[str] = None
    catatan_kc:       str = ""
    harga_jual:       Optional[int] = None
    product_link:     Optional[str] = None
    cabang:           str
    dibuat_oleh:      str
    disetujui_oleh_kc: Optional[str] = None
    disetujui_at_kc:   Optional[str] = None
    approved_by:      Optional[str] = None
    approved_at:      Optional[str] = None
    created_at:       str
    updated_at:       Optional[str] = None
