from fastapi import APIRouter, Depends

from app.dependencies import CurrentUser, current_user
from app.schemas.auth import CurrentUserOut

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/me", response_model=CurrentUserOut)
async def get_me(
    user: CurrentUser = Depends(current_user),
) -> CurrentUserOut:
    """The identity this service resolved from the caller's bearer token.

    With AUTH_MODE=auth_service the token has already been verified by
    nexby-auth-service, including revocation and the X-Device-Fingerprint
    binding. The returned IDs are this service's stable integer mapping of the
    auth-service UUIDs, not the UUIDs themselves.
    """
    return CurrentUserOut(
        id=user.id,
        role=user.role,
        admin_id=user.admin_id,
        agent_id=user.agent_id,
        company_name=user.company_name,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        organization_slug=user.organization_slug,
        auth_user_id=user.auth_user_id,
    )
