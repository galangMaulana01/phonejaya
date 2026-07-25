from pydantic import BaseModel, field_validator
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


class CustomerStatusEnum(str, Enum):
    pending   = "Pending"
    verified  = "Verified"
    rejected  = "Rejected"


class CustomerCreateRequest(BaseModel):
    nama:   str
    kontak: str
    cabang: str

    @field_validator("nama")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nama tidak boleh kosong")
        return v.strip()


class CustomerVerifyRequest(BaseModel):
    action: Literal["approve"]


class CustomerRejectRequest(BaseModel):
    action: Literal["reject"]
    reason: str

    @field_validator("reason")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Alasan reject wajib diisi")
        return v.strip()


class CustomerResubmitRequest(BaseModel):
    pass


class StatusHistoryItem(BaseModel):
    status_lama: str
    status_baru: str
    actor_id: str
    actor_name: str
    actor_role: str
    timestamp: str
    reason: Optional[str] = None


class CustomerResponse(BaseModel):
    id: str
    nama: str
    kontak: str
    cabang: str
    status: CustomerStatusEnum
    points: int = 0
    created_at: str
    verified_at: Optional[str] = None
    verified_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_reason: Optional[str] = None
    status_history: List[StatusHistoryItem] = []


class CustomerListItem(BaseModel):
    id: str
    nama: str
    kontak: str
    cabang: str
    status: CustomerStatusEnum
    points: int
    created_at: str
    verified_at: Optional[str] = None
    verified_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_reason: Optional[str] = None


from typing import Optional