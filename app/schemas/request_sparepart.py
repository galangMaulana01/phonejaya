from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum


class StatusRequestEnum(str, Enum):
    pending  = "Pending"
    diterima = "Diterima"
    ditolak  = "Ditolak"


class RequestSparepartCreateRequest(BaseModel):
    tipe:       str
    sp_id:      Optional[str] = None
    nama_sp:    str
    jumlah:     int = 1
    keterangan: str = ""
    cabang:     str = "JYP"

    @field_validator("nama_sp")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip(): raise ValueError("Nama tidak boleh kosong")
        return v.strip()


class RequestSparepartResponseRequest(BaseModel):
    status:         StatusRequestEnum
    estimasi_tiba:  Optional[str] = None
    catatan:        str = ""


class RequestSparepartResponse(BaseModel):
    id:             str
    req_id:         str
    tipe:           str
    sp_id:          Optional[str] = None
    nama_sp:        str
    jumlah:         int
    keterangan:     str
    status:         str
    estimasi_tiba:  Optional[str] = None
    catatan_kc:     str = ""
    cabang:         str
    dibuat_oleh:    str
    created_at:     str
    updated_at:     Optional[str] = None
