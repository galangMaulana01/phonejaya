from pydantic import BaseModel, field_validator
from typing import Optional
import re


class KaryawanCreateRequest(BaseModel):
    nama:     str
    username: str
    jabatan:  str = "Kasir"
    cabang:   str = "JYP"
    gaji:     int = 0
    password: str = ""

    @field_validator("nama")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nama tidak boleh kosong")
        return v.strip()

    @field_validator("jabatan")
    @classmethod
    def jabatan_valid(cls, v: str) -> str:
        allowed = ["Kasir", "Teknisi", "Owner", "Admin", "Influencer"]
        if v not in allowed:
            raise ValueError(f"Jabatan harus salah satu: {', '.join(allowed)}")
        return v

    @field_validator("password")
    @classmethod
    def password_ok(cls, v: str) -> str:
        if v and len(v) < 6:
            raise ValueError("Password minimal 6 karakter")
        return v


class KaryawanResponse(BaseModel):
    id: str
    nama: str
    username: str
    jabatan: str
    cabang: str
    gaji: int
    aktif: bool
    bergabung: str


class ResetPasswordRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def password_ok(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password minimal 6 karakter")
        return v
