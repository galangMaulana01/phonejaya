from pydantic import BaseModel, field_validator
from typing import Optional, List
from enum import Enum


class StatusTransferEnum(str, Enum):
    pending  = "Pending"
    diterima = "Diterima"
    ditolak  = "Ditolak"


class TransferUnitItem(BaseModel):
    unit_id: str

    @field_validator("unit_id")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("unit_id tidak boleh kosong")
        return v.strip().upper()


class TransferStokCreateRequest(BaseModel):
    cabang_tujuan: str
    unit_ids:      List[TransferUnitItem]
    catatan:       str = ""

    @field_validator("cabang_tujuan")
    @classmethod
    def cabang_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Cabang tujuan wajib diisi")
        return v.strip().upper()

    @field_validator("unit_ids")
    @classmethod
    def units_not_empty(cls, v: List[TransferUnitItem]) -> List[TransferUnitItem]:
        if not v:
            raise ValueError("Minimal 1 unit harus dipilih")
        if len(v) > 50:
            raise ValueError("Maksimal 50 unit per transfer")
        return v


class TransferStokRespondRequest(BaseModel):
    status:  StatusTransferEnum
    catatan: str = ""


# ── Response ──────────────────────────────────────────────────────────────────

class TransferUnitDetail(BaseModel):
    unit_id_asal:   str
    unit_id_baru:   Optional[str] = None   # diisi setelah Diterima
    merk:           str
    tipe:           str
    storage:        str
    imei:           str
    kondisi:        str
    status_unit:    str                    # status unit saat transfer dibuat


class TransferStokResponse(BaseModel):
    id:             str
    transfer_id:    str
    cabang_asal:    str
    cabang_tujuan:  str
    units:          List[TransferUnitDetail]
    jumlah:         int
    status:         str
    catatan:        str
    catatan_respon: str
    dibuat_oleh:    str
    direspon_oleh:  str
    created_at:     str
    updated_at:     Optional[str] = None
