from pydantic import BaseModel, field_validator
from typing import Optional, List
from enum import Enum


class StatusServiceEnum(str, Enum):
    masuk    = "Masuk"
    diagnosa = "Diagnosa"
    proses   = "Proses"
    selesai  = "Selesai"
    diambil  = "Diambil"


class ServiceCreateRequest(BaseModel):
    nama_customer:    str
    kontak_customer:  str
    merk:             str
    tipe:             str
    keluhan:          str
    catatan_kerusakan: str = ""
    estimasi_biaya:   int = 0
    cabang:           str = "JYP"

    @field_validator("nama_customer", "merk", "tipe", "keluhan")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        return v.strip()


class ServiceUpdateRequest(BaseModel):
    status:            Optional[StatusServiceEnum] = None
    catatan_kerusakan: Optional[str] = None
    estimasi_biaya:    Optional[int] = None
    teknisi:           Optional[str] = None


class ServiceResponse(BaseModel):
    id: str
    service_id: str
    nama_customer: str
    kontak_customer: str
    merk: str
    tipe: str
    keluhan: str
    catatan_kerusakan: str
    estimasi_biaya: int
    status: str
    teknisi: str
    foto_urls: List[str]
    cabang: str
    created_at: str
    updated_at: Optional[str] = None
