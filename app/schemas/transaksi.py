from pydantic import BaseModel
from typing import Optional, List


class TransaksiCreateRequest(BaseModel):
    """Transaksi jual HP."""
    unit_id:  str
    imei:     str
    catatan:  str = ""


class TransaksiSparepartItem(BaseModel):
    sp_id:   str
    jumlah:  int = 1


class TransaksiSparepartRequest(BaseModel):
    """Transaksi jual sparepart/aksesoris langsung."""
    items:    List[TransaksiSparepartItem]
    catatan:  str = ""


class TransaksiResponse(BaseModel):
    id:          str
    trx_id:      str
    tipe:        str          # "unit" | "sparepart"
    unit_id:     Optional[str] = None
    unit_label:  str
    kasir:       str
    harga_jual:  int
    harga_modal: int
    profit:      int
    waktu:       str
    catatan:     str
    cabang:      str
