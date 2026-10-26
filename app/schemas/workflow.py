from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkflowStepInfo(BaseModel):
    name: str
    status: str                   # pending | running | completed | failed | skipped
    result: dict | None = None
    error: str | None = None


class WorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    txn_id: str
    admin_id: int
    user_id: int
    flow_name: str
    status: str                   # pending | running | completed | partial | failed
    current_step: str | None = None
    steps: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkflowTriggerRequest(BaseModel):
    """Optional standalone trigger (not tied to visitor creation)."""

    txn_Id: str
    payload: dict = Field(default_factory=dict)