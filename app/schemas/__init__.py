from app.schemas.analysis import AnalysisAccepted, DocumentAnalyzeRequest, DocumentAnalysisOut, \
    DocumentAnalysisListItem, ImageAnalyzeRequest, ImageAnalysisOut, ImageAnalysisListItem
from app.schemas.common import (
    ErrorResponse,
    PaginatedResponse,
    PaginationMeta,
    StatusResponse,
)
from app.schemas.auth import CurrentUserOut
from app.schemas.document import Block, DocumentAccepted, DocumentCreateRequest, DocumentJobOut, DocumentListOut, \
    DocumentMetadata, DocumentOutput, HeadingBlock, ParagraphBlock, ListBlock, TableBlock, PageBreakBlock, ImageBlock
from app.schemas.event import EventCreate, EventOut, EventUpdate
from app.schemas.extraction import ExtractionAccepted, ExtractionCreateRequest, ExtractionListItem, ExtractionOut, \
    ExtractionResultField, ExtractionFieldEdit, ExtractionPatchRequest
from app.schemas.image import ImageAccepted, ImageCreateRequest, ImageJobOut, ImageListOut, ImageTypeInfo, \
    ImageTypeListOut
from app.schemas.stats import StatsOverviewOut, StatusCountItem, TemplateUsageItem, NeedsReviewCountOut
from app.schemas.template import TemplateCategoryListOut, TemplateCategoryOut, TemplateField, TemplateListItem, \
    TemplateOut
from app.schemas.visitor import (
    AddressOut,
    DuplicateInfo,
    EventDetails,
    EventInfo,
    FlowOptions,
    SecondaryOCROut,
    VisitorAccepted,
    VisitorCreate,
    VisitorListOut,
    VisitorOut,
    VisitorUpdate,
    VisitingCardInput,
    VisitingCardOut,
    VisitingCardPrimary,
    VisitingCardSecondary,
)
from app.schemas.ocr import (
    AddressOCR,
    OCRCallbackPayload,
    OCRJobAccepted,
    OCRJobDetail,
    OCRResult,
)
from app.schemas.workflow import (
    WorkflowRunOut,
    WorkflowStepInfo,
    WorkflowTriggerRequest,
)
from app.schemas.flow import FlowOut

__all__ = [
    # common
    "ErrorResponse",
    "PaginatedResponse",
    "PaginationMeta",
    "StatusResponse",
    # auth
    "CurrentUserOut",
    # event
    "EventCreate",
    "EventUpdate",
    "EventOut",
    # visitor
    "AddressOut",
    "DuplicateInfo",
    "EventDetails",
    "EventInfo",
    "FlowOptions",
    "SecondaryOCROut",
    "VisitorAccepted",
    "VisitorCreate",
    "VisitorListOut",
    "VisitorOut",
    "VisitorUpdate",
    "VisitingCardInput",
    "VisitingCardOut",
    "VisitingCardPrimary",
    "VisitingCardSecondary",
    # ocr
    "AddressOCR",
    "OCRCallbackPayload",
    "OCRJobAccepted",
    "OCRJobDetail",
    "OCRResult",
    # workflow
    "WorkflowRunOut",
    "WorkflowStepInfo",
    "WorkflowTriggerRequest",
    # document
    "Block",
    "DocumentAccepted",
    "DocumentCreateRequest",
    "DocumentJobOut",
    "DocumentListOut",
    "DocumentMetadata",
    "DocumentOutput",
    "HeadingBlock",
    "ParagraphBlock",
    "ListBlock",
    "TableBlock",
    "PageBreakBlock",
    "ImageBlock",
    # image
    "ImageAccepted",
    "ImageCreateRequest",
    "ImageJobOut",
    "ImageListOut",
    "ImageTypeInfo",
    "ImageTypeListOut",
    # analysis
    "AnalysisAccepted",
    "DocumentAnalyzeRequest",
    "DocumentAnalysisOut",
    "DocumentAnalysisListItem",
    "ImageAnalyzeRequest",
    "ImageAnalysisOut",
    "ImageAnalysisListItem",
    # Template
    "TemplateCategoryListOut",
    "TemplateCategoryOut",
    "TemplateField",
    "TemplateListItem",
    "TemplateOut",

    # Extraction
    "ExtractionAccepted",
    "ExtractionCreateRequest",
    "ExtractionListItem",
    "ExtractionOut",
    "ExtractionResultField",
    "ExtractionFieldEdit",
    "ExtractionPatchRequest",
    # State
    "StatsOverviewOut",
    "StatusCountItem",
    "TemplateUsageItem",

    "NeedsReviewCountOut",
]
