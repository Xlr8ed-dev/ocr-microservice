"""S3 helpers for presigned uploads, downloads, and URL validation."""

import logging
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings


logger = logging.getLogger(__name__)


_s3_client = None


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        region = settings.AWS_S3_REGION_NAME
        _s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=region,
            # Force regional endpoint so presigned URLs always include the region
            endpoint_url=f"https://s3.{region}.amazonaws.com",
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
            ),
        )
    return _s3_client


# =========================================================
# KEYS & URLS
# =========================================================

def build_file_key(admin_id: int, file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "bin"
    unique_id = uuid.uuid4()
    return f"ocr-uploads/{admin_id}/{unique_id}.{ext}"


def build_file_url(file_key: str) -> str:
    return (
        f"https://{settings.AWS_STORAGE_BUCKET_NAME}."
        f"s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{file_key}"
    )


def is_our_s3_url(url: str) -> bool:
    if not url:
        return False
    return url.startswith(f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.")


def extract_key_from_url(url: str) -> str | None:
    if not is_our_s3_url(url):
        return None
    parts = url.split(".amazonaws.com/", 1)
    if len(parts) == 2:
        return parts[1].split("?")[0]
    return None


def is_admin_owner_of_key(admin_id: int, file_key: str) -> bool:
    return file_key.startswith(f"ocr-uploads/{admin_id}/")


# =========================================================
# PRESIGNED POST (UPLOAD)
# =========================================================

def generate_presigned_post(
    admin_id: int,
    file_name: str,
    content_type: str,
    *,
    expires_in: int | None = None,
) -> tuple[str, dict, str]:
    s3 = get_s3_client()
    file_key = build_file_key(admin_id, file_name)
    expires_in = expires_in or settings.S3_PRESIGN_EXPIRES_SECONDS
    max_bytes = settings.S3_UPLOAD_MAX_MB * 1024 * 1024

    conditions = [
        ["content-length-range", 1, max_bytes],
        {"Content-Type": content_type},
        {"key": file_key},
    ]

    try:
        response = s3.generate_presigned_post(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=file_key,
            Fields={"Content-Type": content_type},
            Conditions=conditions,
            ExpiresIn=expires_in,
        )
    except ClientError as exc:
        logger.exception("Failed to generate presigned POST for %s", file_name)
        raise RuntimeError(f"S3 presign failed: {exc}") from exc

    # Defensively rewrite host to include the region
    url = response["url"]
    generic_host = "s3.amazonaws.com"
    regional_host = f"s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com"
    if generic_host in url:
        url = url.replace(generic_host, regional_host)

    return url, response["fields"], file_key


# =========================================================
# PRESIGNED GET (DOWNLOAD)
# =========================================================

def generate_presigned_get(file_key: str, expires_in: int = 900) -> str:
    s3 = get_s3_client()
    try:
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": file_key},
            ExpiresIn=expires_in,
        )
    except ClientError as exc:
        logger.exception("Failed to generate presigned GET for %s", file_key)
        raise RuntimeError(f"S3 presign GET failed: {exc}") from exc

    # Defensive: ensure the region is in the URL
    generic_host = "s3.amazonaws.com"
    regional_host = f"s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com"
    if generic_host in url:
        url = url.replace(generic_host, regional_host)

    return url


def normalize_download_url(url: str) -> str:
    key = extract_key_from_url(url)
    if key:
        return generate_presigned_get(key)
    return url