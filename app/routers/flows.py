from fastapi import APIRouter, Depends

from app.dependencies import CurrentUser, current_user
from app.flows.registry import FLOWS
from app.schemas.common import StatusResponse
from app.schemas.flow import FlowOut


router = APIRouter(prefix="/flows", tags=["Flows"])


class FlowListResponse(StatusResponse):
    data: list[FlowOut]


@router.get("", response_model=FlowListResponse)
async def list_flows(
    user: CurrentUser = Depends(current_user),
) -> FlowListResponse:
    """Return the flows available to this user.

    Phase 0: all flows returned (no plan filtering).
    Phase 2+: filter by user's plan via Billing.
    """
    return FlowListResponse(
        data=[
            FlowOut(
                name=f.name,
                label=f.label,
                description=f.description,
                requires_plan=f.requires_plan,
                allows_whatsapp=f.allows_whatsapp,
                allows_email=f.allows_email,
            )
            for f in FLOWS.values()
        ],
    )