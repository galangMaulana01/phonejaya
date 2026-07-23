from pydantic import BaseModel, field_validator
from typing import Optional


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        return v.strip()


class UserPublic(BaseModel):
    id: str
    username: str
    name: str
    role: str
    cabang: str
    foto_profil_url: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class ProfileUpdateRequest(BaseModel):
    """Request untuk update profil sendiri - foto_profil_url dan nama yang bisa diubah."""
    foto_profil_url: Optional[str] = None
    name: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    """Request ganti password - wajib verifikasi password lama."""
    password_lama: str
    password_baru: str
    password_konfirmasi: str

    @field_validator("password_baru")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password minimal 6 karakter")
        return v

    @field_validator("password_konfirmasi")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if v != info.data.get("password_baru"):
            raise ValueError("Konfirmasi password tidak cocok")
        return v
