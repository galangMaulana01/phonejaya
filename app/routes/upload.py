"""
Upload routes for backend-mediated Cloudinary uploads.
All image uploads go through this endpoint for signed Cloudinary uploads.
"""

from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException, status
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.database import get_db
from app.config.settings import settings
from app.schemas.common import ok
from app.middlewares.auth import require_any
from app.services.cloudinary_service import (
    upload_image,
    CloudinaryServiceError,
    delete_image,
)

router = APIRouter(prefix="/upload", tags=["Upload"])


# Allowed image MIME types
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

# Maximum file size: 10 MB
MAX_FILE_SIZE = 10 * 1024 * 1024

# Folder mapping for different upload types
FOLDER_MAP = {
    "unit": "jayaphone/units",
    "transaction": "jayaphone/transactions",
    "service_before": "jayaphone/service/before",
    "service_after": "jayaphone/service/after",
    "sparepart": "jayaphone/spareparts",
    "profile": "jayaphone/users/profiles",
    "customer": "jayaphone/customers",
    "general": "jayaphone/general",
}


@router.post("/image", response_model=dict)
async def upload_single_image(
    file: UploadFile = File(...),
    upload_type: str = Form("general"),
    folder: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    context_key: Optional[str] = Form(None),
    context_value: Optional[str] = Form(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_any),
):
    """
    Upload a single image via backend to Cloudinary.
    
    Args:
        file: Image file to upload
        upload_type: Type of upload (unit, transaction, service_before, service_after, etc.)
        folder: Override default folder (optional)
        tags: Comma-separated tags (optional)
        context_key: Context key for metadata (optional)
        context_value: Context value for metadata (optional)
    
    Returns:
        Upload result with secure_url, public_id, etc.
    """
    # Validate file type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file.content_type} not allowed. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}"
        )
    
    # Read and validate file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)} MB"
        )
    
    # Determine folder
    target_folder = folder or FOLDER_MAP.get(upload_type, FOLDER_MAP["general"])
    
    # Parse tags
    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    
    # Build context
    context = None
    if context_key and context_value:
        context = {context_key: context_value}
    
    # Add user info to context
    user_name = user.get("name") or user.get("username", "")
    if context:
        context["uploaded_by"] = user_name
    else:
        context = {"uploaded_by": user_name}
    
    try:
        result = await upload_image(
            file_content=content,
            folder=target_folder,
            tags=tag_list,
            context=context,
        )
        
        return ok({
            "secure_url": result["secure_url"],
            "public_id": result.get("public_id"),
            "format": result.get("format"),
            "width": result.get("width"),
            "height": result.get("height"),
            "bytes": result.get("bytes"),
            "folder": target_folder,
        }, message="Image uploaded successfully")
    
    except CloudinaryServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.post("/images", response_model=dict)
async def upload_multiple_images(
    files: List[UploadFile] = File(...),
    upload_type: str = Form("general"),
    folder: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    context_key: Optional[str] = Form(None),
    context_value: Optional[str] = Form(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_any),
):
    """
    Upload multiple images via backend to Cloudinary.
    
    Args:
        files: List of image files to upload
        upload_type: Type of upload (unit, transaction, service_before, service_after, etc.)
        folder: Override default folder (optional)
        tags: Comma-separated tags (optional)
        context_key: Context key for metadata (optional)
        context_value: Context value for metadata (optional)
    
    Returns:
        List of upload results
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )
    
    if len(files) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 files per request"
        )
    
    # Validate all files first
    for file in files:
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {file.filename}: type {file.content_type} not allowed"
            )
    
    # Read all files and validate sizes
    contents = []
    for file in files:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {file.filename} too large. Maximum: {MAX_FILE_SIZE // (1024*1024)} MB"
            )
        contents.append((file.filename, file.content_type, content))
    
    # Determine folder
    target_folder = folder or FOLDER_MAP.get(upload_type, FOLDER_MAP["general"])
    
    # Parse tags
    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    
    # Build context
    context = None
    if context_key and context_value:
        context = {context_key: context_value}
    
    user_name = user.get("name") or user.get("username", "")
    if context:
        context["uploaded_by"] = user_name
    else:
        context = {"uploaded_by": user_name}
    
    results = []
    errors = []
    
    for filename, content_type, content in contents:
        try:
            result = await upload_image(
                file_content=content,
                folder=target_folder,
                tags=tag_list,
                context=context,
            )
            results.append({
                "filename": filename,
                "secure_url": result["secure_url"],
                "public_id": result.get("public_id"),
                "format": result.get("format"),
                "width": result.get("width"),
                "height": result.get("height"),
                "bytes": result.get("bytes"),
            })
        except CloudinaryServiceError as e:
            errors.append({"filename": filename, "error": e.message})
        except Exception as e:
            errors.append({"filename": filename, "error": str(e)})
    
    return ok({
        "uploaded": results,
        "errors": errors,
        "total": len(results),
        "failed": len(errors),
    }, message=f"Uploaded {len(results)} of {len(files)} files")


@router.delete("/image", response_model=dict)
async def delete_uploaded_image(
    public_id: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_any),
):
    """
    Delete an uploaded image from Cloudinary.
    
    Args:
        public_id: Cloudinary public_id of the image to delete
    
    Returns:
        Deletion result
    """
    try:
        result = await delete_image(public_id)
        return ok(result, message="Image deleted successfully")
    except CloudinaryServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delete failed: {str(e)}"
        )


@router.get("/signature", response_model=dict)
async def get_upload_signature(
    folder: str = "jayaphone/general",
    public_id: Optional[str] = None,
    timestamp: Optional[int] = None,
    user: dict = Depends(require_any),
):
    """
    Get a signed upload signature for direct frontend uploads (if needed).
    
    Note: Primary flow is backend-mediated upload via POST /upload/image.
    This endpoint is for advanced use cases where direct signed upload is needed.
    
    Args:
        folder: Cloudinary folder
        public_id: Optional custom public_id
        timestamp: Optional timestamp (defaults to current time)
    
    Returns:
        Signature, timestamp, and API key for signed upload
    """
    import cloudinary.utils
    import time
    
    if timestamp is None:
        timestamp = int(time.time())
    
    params = {
        "folder": folder,
        "timestamp": timestamp,
    }
    
    if public_id:
        params["public_id"] = public_id
    
    signature = cloudinary.utils.api_sign_request(params, settings.CLOUDINARY_API_SECRET)
    
    return ok({
        "signature": signature,
        "timestamp": timestamp,
        "api_key": settings.CLOUDINARY_API_KEY,
        "cloud_name": settings.CLOUDINARY_CLOUD_NAME,
        "folder": folder,
    }, message="Upload signature generated")


from typing import Optional