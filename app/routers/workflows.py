from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.schemas.workflow import WorkflowRunOut, WorkflowTriggerRequest
from app.services import workflow_service


router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.post(
    "/{flow_name}",
    response_model=WorkflowRunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_workflow(
    flow_name: str,
    data: WorkflowTriggerRequest,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunOut:
    """Standalone workflow trigger, not tied to visitor creation.
    Rarely used — most workflows fire from the OCR callback path."""
    raise NotImplementedError(
        "Workflows are triggered automatically after OCR completion. "
        "Standalone trigger not enabled in v1."
    )


@router.get("/{run_id}", response_model=WorkflowRunOut)
async def get_workflow_run(
    run_id: str,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunOut:
    run = await workflow_service.get_run(db, user, run_id)
    return WorkflowRunOut.model_validate(run)