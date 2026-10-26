"""Seed the 8 built-in templates.

Run:  python -m app.scripts.seed_templates
"""

import asyncio
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Template


logger = logging.getLogger(__name__)


# =========================================================
# TEMPLATE DEFINITIONS
# =========================================================

TEMPLATES = [
    {
        "id": "resume_screener",
        "name": "Resume Screener",
        "category": "Resumes",
        "description": "Extract structured candidate data from resumes.",
        "fields": [
            {"key": "full_name",     "label": "Full name",     "type": "string", "required": True,  "description": "The candidate's full name as printed."},
            {"key": "job_title",     "label": "Job title",     "type": "string", "required": False, "description": "Current or last job title."},
            {"key": "email",         "label": "Email address", "type": "email",  "required": False, "description": "The candidate's email address."},
            {"key": "phone",         "label": "Phone number",  "type": "phone",  "required": False, "description": "The candidate's phone number."},
            {"key": "location",      "label": "Location",      "type": "string", "required": False, "description": "City / state / country."},
            {"key": "summary",       "label": "Summary",       "type": "string", "required": False, "description": "Profile summary or objective from the resume."},
            {"key": "experience",    "label": "Employment history", "type": "list", "required": False, "description": "Repeat for each role: company_name, role, start_date, end_date, description."},
            {"key": "education",     "label": "Education",     "type": "list",   "required": False, "description": "Repeat for each degree: institution, degree, field, year."},
            {"key": "skills",        "label": "Skills",        "type": "list",   "required": False, "description": "List of technical and soft skills."},
            {"key": "certifications","label": "Certifications","type": "list",   "required": False, "description": "Professional certifications."},
            {"key": "languages",     "label": "Languages",     "type": "list",   "required": False, "description": "Spoken languages."},
            {"key": "linkedin",      "label": "LinkedIn",      "type": "string", "required": False, "description": "LinkedIn profile URL."},
            {"key": "portfolio",     "label": "Portfolio / website", "type": "string", "required": False, "description": "Portfolio or personal website URL."},
            {"key": "references",    "label": "References",    "type": "string", "required": False, "description": "References if listed."},
        ],
        "sample_doc_url": None,
    },
    {
        "id": "business_card_extraction",
        "name": "Business Card Extraction",
        "category": "Business cards",
        "description": "Extract contact details from a business card.",
        "fields": [
            {"key": "full_name",   "label": "Full name",   "type": "string", "required": True,  "description": "The person's name."},
            {"key": "job_title",   "label": "Job title",   "type": "string", "required": False, "description": "Designation on the card."},
            {"key": "company",     "label": "Company",     "type": "string", "required": False, "description": "Company name."},
            {"key": "phone",       "label": "Phone number","type": "phone",  "required": False, "description": "Primary phone (normalize to E.164)."},
            {"key": "email",       "label": "Email address","type": "email", "required": False, "description": "Email address."},
            {"key": "website",     "label": "Website",     "type": "string", "required": False, "description": "Website URL."},
            {"key": "address",     "label": "Address",     "type": "string", "required": False, "description": "Street + city + state + postal code + country."},
            {"key": "social",      "label": "Social handles","type": "list", "required": False, "description": "LinkedIn, Twitter, Instagram, etc."},
        ],
        "sample_doc_url": None,
    },
    {
        "id": "invoice_extraction",
        "name": "Invoice Extraction",
        "category": "Invoices & billing",
        "description": "Extract vendor, line items, totals from an invoice.",
        "fields": [
            {"key": "vendor_name",     "label": "Vendor name",     "type": "string", "required": True,  "description": "Name of the seller."},
            {"key": "vendor_address",  "label": "Vendor address",  "type": "string", "required": False, "description": "Full address of the seller."},
            {"key": "vendor_gst",      "label": "Vendor GST / tax ID", "type": "string", "required": False, "description": "Vendor tax identifier."},
            {"key": "invoice_number",  "label": "Invoice number",  "type": "string", "required": True,  "description": "Invoice identifier."},
            {"key": "invoice_date",    "label": "Invoice date",    "type": "date",   "required": True,  "description": "Date of invoice."},
            {"key": "due_date",        "label": "Due date",        "type": "date",   "required": False, "description": "Payment due date."},
            {"key": "currency",        "label": "Currency",        "type": "string", "required": False, "description": "ISO 4217 currency code."},
            {"key": "line_items",      "label": "Line items",      "type": "list",   "required": True,  "description": "Repeat for each line item: description, quantity, unit_price, amount."},
            {"key": "subtotal",        "label": "Subtotal",        "type": "number", "required": False, "description": "Subtotal before tax."},
            {"key": "tax",             "label": "Tax / VAT",       "type": "number", "required": False, "description": "Total tax amount."},
            {"key": "total",           "label": "Total",           "type": "number", "required": True,  "description": "Grand total including tax."},
        ],
        "sample_doc_url": None,
    },
    {
        "id": "purchase_order_extraction",
        "name": "Purchase Order Extraction",
        "category": "Invoices & billing",
        "description": "Extract PO number, buyer, seller, items and totals.",
        "fields": [
            {"key": "po_number",       "label": "PO number",       "type": "string", "required": True,  "description": "Purchase order identifier."},
            {"key": "po_date",         "label": "PO date",         "type": "date",   "required": False, "description": "Date PO was issued."},
            {"key": "buyer_name",      "label": "Buyer name",      "type": "string", "required": False, "description": "Company issuing the PO."},
            {"key": "seller_name",     "label": "Seller name",     "type": "string", "required": False, "description": "Vendor receiving the PO."},
            {"key": "line_items",      "label": "Line items",      "type": "list",   "required": True,  "description": "Repeat for each item: description, quantity, unit_price, amount."},
            {"key": "subtotal",        "label": "Subtotal",        "type": "number", "required": False, "description": "Subtotal."},
            {"key": "tax",             "label": "Tax",             "type": "number", "required": False, "description": "Tax amount."},
            {"key": "total",           "label": "Total",           "type": "number", "required": True,  "description": "Grand total."},
            {"key": "delivery_terms",  "label": "Delivery terms",  "type": "string", "required": False, "description": "Delivery terms / timeline."},
        ],
        "sample_doc_url": None,
    },
    {
        "id": "kyc_document_extraction",
        "name": "KYC Document Extraction",
        "category": "Identity & KYC",
        "description": "Extract identity details from a KYC document.",
        "fields": [
            {"key": "document_type",    "label": "Document type",   "type": "string", "required": False, "description": "Passport, Aadhaar, PAN, driving licence, etc."},
            {"key": "full_name",        "label": "Full name",       "type": "string", "required": True,  "description": "Name as printed on the document."},
            {"key": "dob",              "label": "Date of birth",   "type": "date",   "required": False, "description": "Date of birth."},
            {"key": "gender",           "label": "Gender",          "type": "string", "required": False, "description": "Gender if printed."},
            {"key": "id_number",        "label": "ID number",       "type": "string", "required": False, "description": "Document identifier."},
            {"key": "address",          "label": "Address",         "type": "string", "required": False, "description": "Address on document."},
            {"key": "issue_date",       "label": "Issue date",      "type": "date",   "required": False, "description": "Date issued."},
            {"key": "expiry_date",      "label": "Expiry date",     "type": "date",   "required": False, "description": "Date of expiry."},
            {"key": "father_name",      "label": "Father's name",   "type": "string", "required": False, "description": "Father's name if present."},
            {"key": "nationality",      "label": "Nationality",     "type": "string", "required": False, "description": "Nationality if printed."},
        ],
        "sample_doc_url": None,
    },
    {
        "id": "gst_registration_extraction",
        "name": "GST Registration Extraction",
        "category": "Identity & KYC",
        "description": "Extract GST registration details from a GST certificate.",
        "fields": [
            {"key": "gstin",            "label": "GSTIN",             "type": "string", "required": True,  "description": "15-character GST identification number."},
            {"key": "legal_name",       "label": "Legal name",        "type": "string", "required": True,  "description": "Registered legal name."},
            {"key": "trade_name",       "label": "Trade name",        "type": "string", "required": False, "description": "Trade name if different."},
            {"key": "registration_date","label": "Registration date", "type": "date",   "required": False, "description": "Date of GST registration."},
            {"key": "business_address", "label": "Principal address", "type": "string", "required": False, "description": "Principal place of business."},
            {"key": "constitution",     "label": "Constitution",      "type": "string", "required": False, "description": "Proprietorship, partnership, private limited, etc."},
            {"key": "state",            "label": "State",             "type": "string", "required": False, "description": "State of registration."},
        ],
        "sample_doc_url": None,
    },
    {
        "id": "rental_agreement_extraction",
        "name": "Rental Agreement Extraction",
        "category": "Legal",
        "description": "Extract parties, property, rent and terms from a rental agreement.",
        "fields": [
            {"key": "landlord_name",     "label": "Landlord name",     "type": "string", "required": True,  "description": "Name of lessor / landlord."},
            {"key": "tenant_name",       "label": "Tenant name",       "type": "string", "required": True,  "description": "Name of lessee / tenant."},
            {"key": "property_address",  "label": "Property address",  "type": "string", "required": True,  "description": "Full address of the rented property."},
            {"key": "property_type",     "label": "Property type",     "type": "string", "required": False, "description": "Flat, house, shop, etc."},
            {"key": "agreement_date",    "label": "Agreement date",    "type": "date",   "required": False, "description": "Date the agreement was signed."},
            {"key": "start_date",        "label": "Lease start date",  "type": "date",   "required": True,  "description": "Start of lease period."},
            {"key": "end_date",          "label": "Lease end date",    "type": "date",   "required": False, "description": "End of lease period."},
            {"key": "monthly_rent",      "label": "Monthly rent",      "type": "number", "required": True,  "description": "Monthly rental amount."},
            {"key": "currency",          "label": "Currency",          "type": "string", "required": False, "description": "ISO 4217 currency."},
            {"key": "security_deposit",  "label": "Security deposit",  "type": "number", "required": False, "description": "Security deposit amount."},
            {"key": "notice_period",     "label": "Notice period",     "type": "string", "required": False, "description": "Notice period for termination."},
            {"key": "amenities",         "label": "Amenities",         "type": "list",   "required": False, "description": "Included amenities."},
            {"key": "special_clauses",   "label": "Special clauses",   "type": "string", "required": False, "description": "Any special terms or conditions."},
        ],
        "sample_doc_url": None,
    },
    {
        "id": "background_verification",
        "name": "Background Verification",
        "category": "Legal",
        "description": "Extract candidate verification data from a background check form.",
        "fields": [
            {"key": "full_name",       "label": "Full name",       "type": "string", "required": True,  "description": "Candidate's full name."},
            {"key": "dob",             "label": "Date of birth",   "type": "date",   "required": False, "description": "Date of birth."},
            {"key": "id_number",       "label": "ID number",       "type": "string", "required": False, "description": "Government ID number."},
            {"key": "address",         "label": "Address",         "type": "string", "required": False, "description": "Current or permanent address."},
            {"key": "phone",           "label": "Phone number",    "type": "phone",  "required": False, "description": "Primary phone."},
            {"key": "email",           "label": "Email address",   "type": "email",  "required": False, "description": "Email address."},
            {"key": "employment_history", "label": "Employment history", "type": "list", "required": False, "description": "Repeat for each role: company, role, start, end, reason_for_leaving."},
            {"key": "education_history",  "label": "Education history",  "type": "list", "required": False, "description": "Repeat for each degree: institution, degree, year."},
            {"key": "criminal_record",    "label": "Criminal record",    "type": "string", "required": False, "description": "Any criminal record disclosed."},
            {"key": "references",         "label": "References",         "type": "list", "required": False, "description": "Reference contacts."},
            {"key": "consent",            "label": "Consent",            "type": "string", "required": False, "description": "Consent text or signature present."},
            {"key": "declaration_date",   "label": "Declaration date",   "type": "date",   "required": False, "description": "Date candidate signed."},
            {"key": "pan",                "label": "PAN",                "type": "string", "required": False, "description": "PAN number if present."},
            {"key": "aadhaar",            "label": "Aadhaar",            "type": "string", "required": False, "description": "Aadhaar number if present."},
            {"key": "passport",           "label": "Passport",           "type": "string", "required": False, "description": "Passport number if present."},
            {"key": "driving_licence",    "label": "Driving licence",    "type": "string", "required": False, "description": "Driving licence number if present."},
        ],
        "sample_doc_url": None,
    },
]


# =========================================================
# SEED
# =========================================================

async def seed_templates() -> None:
    async with AsyncSessionLocal() as db:
        for t in TEMPLATES:
            existing = await db.scalar(
                select(Template).where(Template.id == t["id"])
            )
            if existing:
                # Update fields — template definitions may evolve
                existing.name = t["name"]
                existing.category = t["category"]
                existing.description = t["description"]
                existing.fields = t["fields"]
                existing.sample_doc_url = t["sample_doc_url"]
                existing.is_active = True
                logger.info("updated template %s", t["id"])
            else:
                db.add(Template(
                    id=t["id"],
                    name=t["name"],
                    category=t["category"],
                    description=t["description"],
                    fields=t["fields"],
                    sample_doc_url=t["sample_doc_url"],
                    is_active=True,
                ))
                logger.info("created template %s", t["id"])
        await db.commit()
    print(f"Seeded {len(TEMPLATES)} templates.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_templates())