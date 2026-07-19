from pydantic import BaseModel, field_validator, HttpUrl
from typing import Optional, List, Literal
from datetime import datetime


class CODRequestCreate(BaseModel):
    """Kasir buat COD request (Beli, Jual, atau Delivery)."""
    type: Literal["beli", "jual", "delivery"]  # MUST be before kurir_id (validator depends on it)
    
    # Common fields
    location: str = "Toko"
    wa_number: str = ""
    screenshot_url: str = ""
    note: Optional[str] = None
    kurir_id: Optional[str] = None  # Required for beli/jual, optional for delivery (broadcast)
    
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
        """kurir_id required for beli/jual, optional for delivery (broadcast)."""
        cod_type = info.data.get("type")
        if cod_type in ("beli", "jual") and not v:
            raise ValueError("kurir_id wajib untuk type beli/jual")
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
        "kurir_menuju_toko", "sedang_diantar", "terkirim"
    ]
    note: Optional[str] = None


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
    items: Optional[List[dict]] = None


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
    kasir_id: str
    kasir_name: str
    kurir_id: Optional[str] = None
    kurir_name: Optional[str] = None
    status_history: List[dict] = []


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