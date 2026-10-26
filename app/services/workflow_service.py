from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser
from app.models import Visitor, WorkflowRun
from app.schemas.visitor import FlowOptions


# =========================================================
# PHASE 5 — implementations go here
# =========================================================

async def start_workflow(
    db: AsyncSession,
    user: CurrentUser,
    visitor: Visitor,
    flow: FlowOptions,
) -> WorkflowRun:
    """Create WorkflowRun (PENDING) and dispatch Celery task."""
    raise NotImplementedError


async def get_run(
    db: AsyncSession, user: CurrentUser, run_id: str,
) -> WorkflowRun:
    raise NotImplementedError