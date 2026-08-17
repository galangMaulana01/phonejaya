from pydantic import BaseModel, field_validator, HttpUrl
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime

from app.schemas.common import MAX_RUPIAH


class CODRequestCreate(BaseModel):
    """Kasir buat COD request (Beli, Jual, atau Delivery)."""
    type: Literal["beli", "jual", "delivery"]  # MUST be before kurir_id (validator depends on it)
    
    # Common fields
    location: str = "Toko"
    wa_number: str = ""
    screenshot_url: str = ""
    note: Optional[str] = None
    # Required for jual, optional for beli/delivery. Delivery starts as
    # broadcast (kurir_id=None) by default — kasir can also manually assign
    # one kurir at creation for a "nego di tempat" delivery (harga_jual sudah
    # tercatat lewat Input Transaksi, tapi kurir yang closing di lokasi).
    kurir_id: Optional[str] = None

    # Type = beli fields
    product_name: Optional[str] = None
    offer_price: Optional[int] = None
    product_link: Optional[str] = None
    
    # Type = delivery fields
    trx_id: Optional[str] = None
    delivery_address: Optional[str] = None
    wa_customer: Optional[str] = None
    
    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in ("beli", "jual", "delivery"):
            raise ValueError("Type harus 'beli', 'jual', atau 'delivery'")
        return v
    
    @field_validator("kurir_id")
    @classmethod
    def validate_kurir_id(cls, v, info):
        """kurir_id required for jual only, optional for beli/delivery (broadcast)."""
        cod_type = info.data.get("type")
        if cod_type == "jual" and not v:
            raise ValueError("kurir_id wajib untuk type jual")
        return v

    @field_validator("offer_price")
    @classmethod
    def offer_price_bounded(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > MAX_RUPIAH):
            raise ValueError(f"Harga tawaran harus antara 0 dan {MAX_RUPIAH:,}")
        return v


class CODStatusUpdate(BaseModel):
    """Kurir update status COD."""
    status: Literal[
        "diterima", "ditolak",
        "kurir_menuju_lokasi", "sudah_bertemu_penjual",
        "barang_akan_dijemput", "barang_sudah_diambil",
        "kurir_sedang_transaksi", "transaksi_berhasil",
        "gagal",
        # Delivery statuses
        "kurir_menuju_toko", "sedang_diantar", "terkirim",
        # Beli approval statuses
        "menunggu_approval_kasir"
    ]
    note: Optional[str] = None
    # Delivery proof-of-handover — required when transitioning a type=delivery
    # COD to "terkirim" (see update_cod_status): photo of the unit handed over
    # + photo with the customer, enforced server-side, not just in the UI.
    foto_urls: Optional[List[str]] = None
    # Optional final price a kurir actually closed at "di tempat" — only
    # meaningful on a type=delivery transition to "terkirim". When present
    # and different from the linked transaksi's recorded harga_jual,
    # update_cod_status calls transaksi_service.amend_deal_price to
    # recompute harga_jual/profit/poin_dapat. None/absent = no change.
    deal_price: Optional[int] = None

    @field_validator("deal_price")
    @classmethod
    def deal_price_bounded(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("Harga deal harus lebih dari 0")
        if v is not None and v > MAX_RUPIAH:
            raise ValueError(f"Harga deal tidak boleh lebih dari {MAX_RUPIAH:,}")
        return v


class CODKurirSubmitBeli(BaseModel):
    """Kurir submit data HP setelah bertemu penjual (type=beli)."""
    deal_price: int  # harga jual yang disepakati
    unit_data: Dict[str, Any]  # {imei, merk, tipe, storage, ram, warna, kondisi_hp, battery, foto_url, ...}

    @field_validator("deal_price")
    @classmethod
    def deal_price_bounded(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Deal price harus lebih dari 0")
        if v > MAX_RUPIAH:
            raise ValueError(f"Deal price tidak boleh lebih dari {MAX_RUPIAH:,}")
        return v


class CODRejectRequest(BaseModel):
    """Kasir reject COD dengan alasan."""
    reason: str  # wajib diisi


class CODRequestList(BaseModel):
    """Item di list COD (Dashboard Kurir / Kasir / Owner)."""
    cod_id: str
    type: str  # beli / jual / delivery
    status: str
    created_at: str
    location: str
    wa_number: str
    screenshot_url: str
    product_name: Optional[str] = None
    offer_price: Optional[int] = None
    kasir_name: str
    kurir_name: Optional[str] = None
    kurir_id: Optional[str] = None
    delivery_address: Optional[str] = None
    wa_customer: Optional[str] = None
    trx_id: Optional[str] = None
    items: Optional[List[dict]] = None
    # Beli-specific
    unit_data: Optional[Dict[str, Any]] = None
    deal_price: Optional[int] = None
    reject_reason: Optional[str] = None


class CODRequestDetail(BaseModel):
    """Detail COD request."""
    cod_id: str
    type: str
    status: str
    created_at: str
    updated_at: str
    location: str
    wa_number: str
    screenshot_url: str
    note: Optional[str] = None
    product_name: Optional[str] = None
    offer_price: Optional[int] = None
    product_link: Optional[str] = None
    trx_id: Optional[str] = None
    delivery_address: Optional[str] = None
    wa_customer: Optional[str] = None
    items: Optional[List[dict]] = None
    unit_data: Optional[Dict[str, Any]] = None
    deal_price: Optional[int] = None
    reject_reason: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    kasir_id: str
    kasir_name: str
    kurir_id: Optional[str] = None
    kurir_name: Optional[str] = None
    status_history: List[dict] = []
    cabang: str = ""


class KurirListItem(BaseModel):
    """Kurir untuk dropdown."""
    kurir_id: str
    kurir_name: str
    cabang: str


class CODRequestResponse(BaseModel):
    """Response saat create COD."""
    cod_id: str
    type: str
    status: str
    created_at: str


class ApproveBeliRequest(BaseModel):
    """Request kasir approve COD beli - full unit data edit."""
    harga_jual: int = 0
    unit_data: Dict[str, Any]
    garansi_toko: int = 7
    catatan: str = ""

    @field_validator("harga_jual")
    @classmethod
    def validate_harga_jual(cls, v, info):
        # Only required if kondisi_hp != 'Repair'
        unit_data = info.data.get("unit_data", {})
        kondisi_hp = unit_data.get("kondisi_hp", "Mulus")
        if kondisi_hp != "Repair" and v <= 0:
            raise ValueError("Harga jual wajib diisi untuk kondisi Mulus")
        if v > MAX_RUPIAH:
            raise ValueError(f"Harga jual tidak boleh lebih dari {MAX_RUPIAH:,}")
        return v