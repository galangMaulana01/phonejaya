from pydantic import BaseModel, field_validator
from typing import Optional


class CabangCreateRequest(BaseModel):
    nama:      str
    kode:      str       # JYP, BN, dll — uppercase
    alamat:    str = ""
    telp:      str = ""

    @field_validator("nama", "kode")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        return v.strip().upper() if len(v.strip()) <= 5 else v.strip()

    @field_validator("kode")
    @classmethod
    def kode_upper(cls, v: str) -> str:
        return v.strip().upper()


class CabangUpdateRequest(BaseModel):
    nama:   Optional[str] = None
    alamat: Optional[str] = None
    telp:   Optional[str] = None
    aktif:  Optional[bool] = None


class AssignKepalaCabangRequest(BaseModel):
    username:  str    # username akun yang akan dijadikan kepala cabang
    nama:      str    # nama lengkap
    password:  str    # password login
    foto_profil_url: Optional[str] = None  # foto profil Kepala Cabang


class CabangResponse(BaseModel):
    id:              str
    nama:            str
    kode:            str
    alamat:          str
    telp:            str
    aktif:           bool
    kepala_cabang:   Optional[str] = None   # nama kepala cabang
    kepala_username: Optional[str] = None   # username kepala cabang
    jumlah_karyawan: int = 0
    created_at:      str = ""
