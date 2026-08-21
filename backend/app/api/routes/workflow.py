"""Product workflow/readiness endpoints shared by Docker and native modes."""

from fastapi import APIRouter

from config import settings
from services.readiness import build_system_readiness


router = APIRouter(tags=["Workflow"])


@router.get("/product-readiness")
async def product_readiness() -> dict:
    """Return non-secret runtime/provider/storage readiness for the UI."""
    return build_system_readiness(settings)


@router.get("/workflow/states")
async def workflow_states() -> dict:
    from services.product_workflow import WORKFLOW_LABELS, WorkflowState

    return {
        "schema_version": "phase8.workflow.v1",
        "states": [
            {"id": state.value, "label": WORKFLOW_LABELS[state]}
            for state in WorkflowState
        ],
    }
