from fastapi import APIRouter, HTTPException

from backend.app.core.config import get_settings
from backend.app.repair.models import RepairProposal, RepairProposalRequest
from backend.app.repair.service import RepairProposalError, propose_repair
from backend.app.dashboard.store import save_proposal

router = APIRouter()


@router.post("/repair/propose", response_model=RepairProposal)
async def propose_accessibility_repair(
    request: RepairProposalRequest,
) -> RepairProposal:
    try:
        proposal = await propose_repair(request, get_settings().gemini_api_key)
        if proposal.repair_type != "repair_not_safe":
            save_proposal(request, proposal)
        return proposal
    except RepairProposalError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
