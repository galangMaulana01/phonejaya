from pydantic import BaseModel, field_validator
from typing import Optional


class CustomerCreateRequest(BaseModel):
    nama:   str
    kontak: str
    cabang: str = ""

    @field_validator("nama")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nama tidak boleh kosong")
        return v.strip()


class CustomerResponse(BaseModel):
    id: str
    nama: str
    kontak: str
    cabang: str
    created_at: str
    points: int = 0
