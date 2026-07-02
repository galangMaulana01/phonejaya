from pydantic import BaseModel
from typing import Optional, List


class TransaksiCreateRequest(BaseModel):
    """Transaksi gabungan: HP +/ sparepart."""
    unit_id:  str = ""          # opsional — kosong kalau jual sparepart saja
    imei:          str = ""
    catatan:       str = ""
    garansi_hari:  int = 7     # 7 atau 30
    biaya_garansi: int = 0     # 0 atau 100000
    customer_nama: str = ""
    customer_kontak: str = ""
    poin_dipakai: int = 0
    sparepart_items: Optional[List["SparepartTrxItem"]] = None  # list sparepart yang dibeli


class SparepartTrxItem(BaseModel):
    sp_id:   str
    jumlah:  int = 1


class TransaksiSparepartItem(BaseModel):
    """Legacy — dipertahankan untuk backward compat."""
    sp_id:   str
    jumlah:  int = 1


class TransaksiSparepartRequest(BaseModel):
    """Legacy — endpoint /sparepart tetap ada untuk backward compat."""
    items:    List[TransaksiSparepartItem]
    catatan:  str = ""


class TransaksiResponse(BaseModel):
    id:          str
    trx_id:      str
    tipe:        str          # "unit" | "sparepart" | "gabungan"
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
    poin_dipakai: int = 0
    poin_dapat: int = 0
    cabang:       str
    sp_items: Optional[list] = None


# Fix forward reference
TransaksiCreateRequest.model_rebuild()
