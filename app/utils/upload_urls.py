"""Validation for references returned by the configured upload pipeline."""
from urllib.parse import urlparse
from fastapi import HTTPException

def ensure_uploaded_asset(url: str | None, field: str = "foto") -> None:
    if not url:
        return
    parsed = urlparse(url)
    # The current frontend receives secure_url from the backend-mediated
    # Cloudinary uploader. Arbitrary remote URLs are not evidence assets.
    if parsed.scheme != "https" or parsed.hostname != "res.cloudinary.com" or not parsed.path.startswith("/"):
        raise HTTPException(status_code=422, detail=f"{field} harus berasal dari upload storage yang diizinkan")

def ensure_uploaded_assets(urls: list[str] | None, field: str = "foto") -> None:
    for url in urls or []:
        ensure_uploaded_asset(url, field)
