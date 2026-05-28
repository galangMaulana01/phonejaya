from pydantic import BaseModel, field_validator
from typing import Optional


class KaryawanCreateRequest(BaseModel):
    nama:     str
    username: str
    jabatan:  str = "Kasir"
    cabang:   str = "JYP"
    gaji:     int = 0

    @field_validator("nama")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nama tidak boleh kosong")
        return v.strip()


class KaryawanResponse(BaseModel):
    id: str
    nama: str
    username: str
    jabatan: str
    cabang: str
    gaji: int
    aktif: bool
    bergabung: str
