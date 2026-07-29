from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum
from datetime import datetime


class ModalHistoryRefType(str, Enum):
    sparepart_approve = "sparepart_approve"
    cod_beli = "cod_beli"
    manual_adjust = "manual_adjust"


class UnitModalHistoryCreateRequest(BaseModel):
    unit_id: str
    sebelum: int
    sesudah: int
    delta: int
    ref_type: ModalHistoryRefType
    ref_id: str
    actor_id: str
    actor_name: str
    actor_role: str
    catatan: str = ""

    @field_validator("sebelum", "sesudah", "delta")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Nilai tidak boleh negatif")
        return v


class UnitModalHistoryResponse(BaseModel):
    id: str
    unit_id: str
    sebelum: int
    sesudah: int
    delta: int
    ref_type: str
    ref_id: str
    actor_id: str
    actor_name: str
    actor_role: str
    catatan: str
    timestamp: str