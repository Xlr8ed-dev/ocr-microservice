from dataclasses import dataclass, field


@dataclass(frozen=True)
class FlowStep:
    name: str
    required: bool = True
    flag: str | None = None


@dataclass(frozen=True)
class FlowDefinition:
    name: str
    label: str
    description: str
    requires_plan: str
    allows_whatsapp: bool = False
    allows_email: bool = False
    steps: tuple[FlowStep, ...] = field(default_factory=tuple)


OCR_STEP = FlowStep(name="ocr", required=True)

FLOWS: dict[str, FlowDefinition] = {
    "ocr_only": FlowDefinition(
        name="ocr_only",
        label="Scan only",
        description="Extract card details and save the visitor.",
        requires_plan="basic",
        steps=(OCR_STEP,),
    ),
    "visitor_quick_scan": FlowDefinition(
        name="visitor_quick_scan",
        label="Scan + save",
        description="Scan the card and save the visitor. No outreach.",
        requires_plan="basic",
        steps=(OCR_STEP,),
    ),
    "visitor_full": FlowDefinition(
        name="visitor_full",
        label="Full workflow",
        description="Scan, save, send WhatsApp and start email campaign.",
        requires_plan="pro",
        allows_whatsapp=True,
        allows_email=True,
        steps=(
            OCR_STEP,
            FlowStep(name="whatsapp", required=False, flag="send_whatsapp"),
            FlowStep(name="email_campaign", required=False, flag="send_email"),
        ),
    ),
}

DEFAULT_FLOW = "ocr_only"


def get_flow(name: str | None) -> FlowDefinition:
    if not name:
        return FLOWS[DEFAULT_FLOW]
    return FLOWS.get(name, FLOWS[DEFAULT_FLOW])


def is_known(name: str | None) -> bool:
    return bool(name) and name in FLOWS
