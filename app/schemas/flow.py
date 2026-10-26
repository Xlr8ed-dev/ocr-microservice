from pydantic import BaseModel


class FlowOut(BaseModel):
    name: str
    label: str
    description: str
    requires_plan: str
    allows_whatsapp: bool = False
    allows_email: bool = False