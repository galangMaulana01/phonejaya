"""
Cloudinary service for signed uploads.
Backend-mediated uploads to Cloudinary using signed URLs.
"""

import cloudinary
import cloudinary.uploader
import cloudinary.api
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status

from app.config.settings import settings


# Configure Cloudinary
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)


class CloudinaryServiceError(Exception):
    """Custom exception for Cloudinary service errors."""
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def upload_image(
    file_content: bytes,
    folder: str = "jayaphone",
    public_id: Optional[str] = None,
    transformation: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
    context: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Upload an image to Cloudinary using signed upload.
    
    Args:
        file_content: Binary content of the image
        folder: Cloudinary folder to upload to
        public_id: Optional custom public_id
        transformation: Optional transformation dict
        tags: Optional list of tags
        context: Optional context metadata
    
    Returns:
        Dict with upload result including secure_url, public_id, etc.
    """
    try:
        # Build upload options
        upload_options = {
            "folder": folder,
            "resource_type": "image",
        }
        
        if public_id:
            upload_options["public_id"] = public_id
        
        if transformation:
            upload_options["transformation"] = transformation
        else:
            # Default transformation: auto format, quality, max width 1200
            upload_options["transformation"] = [
                {"width": 1200, "crop": "limit"},
                {"quality": "auto", "fetch_format": "auto"}
            ]
        
        if tags:
            upload_options["tags"] = tags
        
        if context:
            upload_options["context"] = context
        
        # Upload to Cloudinary
        result = cloudinary.uploader.upload(
            file_content,
            **upload_options
        )
        
        return {
            "secure_url": result.get("secure_url"),
            "public_id": result.get("public_id"),
            "format": result.get("format"),
            "width": result.get("width"),
            "height": result.get("height"),
            "bytes": result.get("bytes"),
            "created_at": result.get("created_at"),
            "folder": folder,
        }
        
    except cloudinary.exceptions.Error as e:
        raise CloudinaryServiceError(f"Cloudinary upload failed: {str(e)}", status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        raise CloudinaryServiceError(f"Upload failed: {str(e)}", status.HTTP_500_INTERNAL_SERVER_ERROR)


async def delete_image(public_id: str) -> Dict[str, Any]:
    """
    Delete an image from Cloudinary by public_id.
    
    Args:
        public_id: Cloudinary public_id of the image
    
    Returns:
        Dict with deletion result
    """
    try:
        result = cloudinary.uploader.destroy(public_id, resource_type="image")
        return {"result": result.get("result"), "public_id": public_id}
    except cloudinary.exceptions.Error as e:
        raise CloudinaryServiceError(f"Cloudinary delete failed: {str(e)}", status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        raise CloudinaryServiceError(f"Delete failed: {str(e)}", status.HTTP_500_INTERNAL_SERVER_ERROR)


async def get_upload_signature(folder: str = "jayaphone", public_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate a signed upload signature for direct frontend uploads (if needed).
    
    Args:
        folder: Cloudinary folder
        public_id: Optional custom public_id
    
    Returns:
        Dict with signature, timestamp, and api_key
    """
    timestamp = int(datetime.now(timezone.utc).timestamp())
    
    params = {
        "timestamp": timestamp,
        "folder": folder,
    }
    
    if public_id:
        params["public_id"] = public_id
    
    # Generate signature
    signature = cloudinary.utils.api_sign_request(params, settings.CLOUDINARY_API_SECRET)
    
    return {
        "signature": signature,
        "timestamp": timestamp,
        "api_key": settings.CLOUDINARY_API_KEY,
        "cloud_name": settings.CLOUDINARY_CLOUD_NAME,
        "folder": folder,
    }


async def get_resource_info(public_id: str) -> Optional[Dict[str, Any]]:
    """
    Get information about a Cloudinary resource.
    
    Args:
        public_id: Cloudinary public_id
    
    Returns:
        Resource info dict or None if not found
    """
    try:
        result = cloudinary.api.resource(public_id, resource_type="image")
        return {
            "public_id": result.get("public_id"),
            "secure_url": result.get("secure_url"),
            "format": result.get("format"),
            "width": result.get("width"),
            "height": result.get("height"),
            "bytes": result.get("bytes"),
            "created_at": result.get("created_at"),
            "tags": result.get("tags", []),
        }
    except cloudinary.exceptions.NotFound:
        return None
    except cloudinary.exceptions.Error as e:
        raise CloudinaryServiceError(f"Cloudinary resource lookup failed: {str(e)}", status.HTTP_500_INTERNAL_SERVER_ERROR)