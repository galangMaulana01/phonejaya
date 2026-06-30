from pydantic import BaseModel
from typing import Optional, List


class TransaksiCreateRequest(BaseModel):
    """Transaksi jual HP."""
    unit_id:  str
    imei:          str
    catatan:       str = ""
    garansi_hari:  int = 7     # 7 atau 30
    biaya_garansi: int = 0     # 0 atau 100000
    customer_nama: str = ""    # nama pembeli (optional - jika baru akan auto-create)
    customer_kontak: str = ""  # kontak pembeli (optional)


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
    catatan:      str
    garansi_hari: int = 7
    biaya_garansi: int = 0
    cabang:       str
