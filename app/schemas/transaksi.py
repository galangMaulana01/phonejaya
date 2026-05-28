from pydantic import BaseModel
from typing import Optional


class TransaksiCreateRequest(BaseModel):
    unit_id:  str
    imei:     str
    catatan:  str = ""


class TransaksiResponse(BaseModel):
    id: str
    trx_id: str
    unit_id: str
    unit_label: str
    kasir: str
    harga_jual: int
    harga_modal: int
    profit: int
    waktu: str
    catatan: str
    cabang: str
