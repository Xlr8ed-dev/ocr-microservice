"""Pre-flight blurry check for image files.

Runs Tesseract on the image and computes the average confidence. If
the average is below a threshold, we skip the expensive vision call
and mark the extraction as `blurry`.

Runs on a downloaded temp file. No AI cost. Cheap.
"""

import logging
import os
import tempfile

import httpx
import pytesseract
from PIL import Image

from app.config import settings
from app.services.s3_service import normalize_download_url

logger = logging.getLogger(__name__)

# =========================================================
# CONSTANTS
# =========================================================

BLURRY_THRESHOLD = 0.5  # average confidence (0–1) below this → blurry
DOWNLOAD_TIMEOUT = 60.0

# Configure pytesseract if the path is set in .env
if settings.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


# =========================================================
# PUBLIC FUNCTION
# =========================================================

async def is_blurry(image_url: str) -> tuple[bool, float]:
    """Download the image and check Tesseract's confidence.

    Returns:
        (is_blurry, avg_confidence)
        - is_blurry: True if avg confidence < BLURRY_THRESHOLD
        - avg_confidence: 0.0–1.0 (0 = couldn't read anything)

    On any failure (download error, Tesseract missing), returns
    (False, 1.0) — i.e. treats the image as OK and lets the AI decide.
    Better to spend an AI call than to reject a good image.
    """
    tmp_path: str | None = None
    try:
        tmp_path = await _download(image_url)

        try:
            img = Image.open(tmp_path)
        except Exception as exc:
            logger.warning("blurry_check: cannot open image: %s", exc)
            return False, 1.0

        try:
            data = pytesseract.image_to_data(
                img,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            logger.warning("blurry_check: Tesseract failed: %s", exc)
            return False, 1.0

        confidences = []
        for c in data.get("conf", []):
            try:
                c_float = float(c)
            except (TypeError, ValueError):
                continue
            # Tesseract returns -1 for "no confidence" — ignore those
            if c_float >= 0:
                confidences.append(c_float / 100.0)

        if not confidences:
            # Tesseract found no text at all → blurry
            return True, 0.0

        avg = sum(confidences) / len(confidences)
        logger.info(
            "blurry_check: url=%s avg_conf=%.3f (n=%d)",
            image_url, avg, len(confidences),
        )
        return avg < BLURRY_THRESHOLD, avg

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# =========================================================
# HELPERS
# =========================================================

async def _download(url: str) -> str:
    """Stream the file to a temp path, return the path."""
    url = normalize_download_url(url)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".img")
    tmp_path = tmp.name
    tmp.close()

    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(tmp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)
    except httpx.HTTPError as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise RuntimeError(f"Download failed: {exc}") from exc

    return tmp_path
