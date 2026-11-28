from typing import TypedDict

from fastapi import APIRouter

from app.api.auth import require_permission
from app.api.deps import ContainerDep
from app.api.routers.incidents import IncidentPrincipal
from app.domain.models import RemediationMode

router = APIRouter(tags=["dashboard"])


class DashboardSession(TypedDict):
    name: str
    can_transition: bool
    can_decide_approval: bool
    remediation_mode: RemediationMode


@router.get("/v1/dashboard/session")
async def dashboard_session(container: ContainerDep, principal: IncidentPrincipal) -> DashboardSession:
    """Return the signed-in client's dashboard capabilities and the configured remediation mode."""
    require_permission(principal, "read")
    return {
        "name": principal.name,
        "can_transition": principal.can("transition"),
        "can_decide_approval": principal.can("approval"),
        "remediation_mode": container.settings.remediation_mode,
    }
