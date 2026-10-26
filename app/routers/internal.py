from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_service_token
from app.schemas.ocr import OCRCallbackPayload
from app.services import ocr_service


router = APIRouter(prefix="/internal", tags=["Internal"])


@router.post(
    "/ocr/callback",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_service_token)],
)
async def ocr_callback(
    payload: OCRCallbackPayload,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await ocr_service.handle_ocr_callback(db, payload)
    return {"status": "ok"}