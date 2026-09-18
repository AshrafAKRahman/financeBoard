"""One HTTP shape for every domain error: RFC 9457 problem details.

A `DomainError` carries a stable `<module>.<code>`; this module maps the code to a status
and a title. Detail text comes from the error, so it must never contain a secret — the
services take care of that, and `tests/api/test_hardening.py` checks it.
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.shared.errors import DomainError

PROBLEM_JSON = "application/problem+json"

# code -> (status, title). Anything unlisted is a 409: a rule was broken, but not one we
# have given a nicer answer to yet.
_STATUSES: dict[str, tuple[int, str]] = {
    "identity.invalid_credentials": (401, "Sign-in failed"),
    "identity.not_authenticated": (401, "Not authenticated"),
    "identity.session_expired": (401, "Session expired"),
    "identity.too_many_attempts": (429, "Too many attempts"),
    "identity.permission_denied": (403, "Permission denied"),
    "identity.company_forbidden": (403, "Company not available"),
    "identity.csrf_check_failed": (403, "Request blocked"),
    "identity.invalid_email": (422, "Invalid email address"),
    "identity.weak_password": (422, "Password too short"),
    "identity.duplicate_email": (409, "Email already in use"),
    "identity.invitation_invalid": (404, "Invitation not found"),
    "identity.invitation_expired": (410, "Invitation expired"),
    "identity.invitation_used": (409, "Invitation already used"),
    "identity.invitation_email_failed": (502, "Invitation email not sent"),
    "identity.role_not_found": (404, "Role not found"),
    "identity.user_not_found": (404, "User not found"),
    "identity.last_administrator": (409, "Last administrator"),
    "identity.user_in_use": (409, "User cannot be deleted"),
    "identity.already_bootstrapped": (409, "Already set up"),
    "audit.append_only": (500, "Audit log is append-only"),
    # Chart of accounts
    "coa.account_not_found": (404, "Account not found"),
    "coa.journal_not_found": (404, "Journal not found"),
    "coa.parent_not_found": (404, "Parent account not found"),
    "coa.template_not_found": (404, "Chart template not found"),
    "coa.company_not_found": (404, "Company not found"),
    "coa.currency_not_found": (404, "Currency not found"),
    "coa.duplicate_code": (409, "Code already used"),
    "coa.account_in_use": (409, "Account is in use"),
    "coa.journal_in_use": (409, "Journal is in use"),
    "coa.account_archived": (409, "Account is archived"),
    "coa.account_is_default": (409, "Account is a company default"),
    "coa.has_children": (409, "Account has children"),
    "coa.chart_not_empty": (409, "Chart is not empty"),
    "coa.invalid_subtype": (422, "Invalid account subtype"),
    "coa.missing_field": (422, "Missing field"),
    "coa.invalid_journal_code": (422, "Invalid journal code"),
    "coa.invalid_journal_type": (422, "Invalid journal type"),
    "coa.parent_not_group": (422, "Parent is not a group account"),
    "coa.parent_type_mismatch": (422, "Parent has a different type"),
    "coa.hierarchy_cycle": (422, "That parent would make a loop"),
    "coa.hierarchy_too_deep": (422, "Chart is too deeply nested"),
    "coa.default_subtype_mismatch": (422, "Account does not suit this default"),
    "coa.default_account_required": (422, "A default account is required"),
    "coa.group_account": (422, "Group accounts cannot be posted to"),
    "coa.unknown_default": (422, "Unknown company default"),
    "coa.invalid_rate": (422, "Invalid exchange rate"),
    "coa.base_currency_rate": (422, "The base currency needs no rate"),
    # Invoicing and VAT
    "invoicing.document_not_found": (404, "Document not found"),
    "invoicing.partner_not_found": (404, "Partner not found"),
    "invoicing.account_not_found": (404, "Account not found"),
    "invoicing.journal_not_found": (404, "Journal not found"),
    "invoicing.template_not_found": (404, "Recurring template not found"),
    "tax.tax_not_found": (404, "Tax not found"),
    "tax.account_not_found": (404, "Tax account not found"),
    "invoicing.duplicate_vendor_reference": (409, "This vendor document is already recorded"),
    "invoicing.posted_immutable": (409, "Issued documents cannot change"),
    "invoicing.already_posted": (409, "Document is already issued"),
    "invoicing.already_cancelled": (409, "Document is already cancelled"),
    "invoicing.not_posted": (409, "Document has not been issued"),
    "invoicing.exceeds_original": (409, "Credits would exceed the document"),
    "invoicing.default_account_missing": (409, "A company default account is missing"),
    "tax.tax_in_use": (409, "Tax is on issued documents"),
    "tax.duplicate_name": (409, "A tax with that name exists"),
    "invoicing.invalid_vat_number": (422, "Invalid VAT number"),
    "invoicing.invalid_line": (422, "Invalid document line"),
    "invoicing.no_lines": (422, "Document has no lines"),
    "invoicing.invalid_type": (422, "Invalid document type"),
    "invoicing.invalid_partner_type": (422, "Invalid partner type"),
    "invoicing.invalid_interval": (422, "Invalid recurrence interval"),
    "invoicing.missing_field": (422, "Missing field"),
    "tax.invalid_rate": (422, "Invalid tax rate"),
    "tax.invalid_type": (422, "Invalid tax type"),
    "tax.invalid_category": (422, "Invalid VAT category"),
    "tax.missing_reason": (422, "A reason is required"),
    "tax.not_effective": (422, "Tax does not apply on this date"),
    "tax.wrong_tax_type": (422, "Wrong tax type for this document"),
    # Payments and reconciliation
    "payments.payment_not_found": (404, "Payment not found"),
    "payments.partner_not_found": (404, "Partner not found"),
    "payments.journal_not_found": (404, "Journal not found"),
    "payments.line_not_found": (404, "Ledger line not found"),
    "payments.reconciliation_not_found": (404, "Match not found"),
    "payments.statement_not_found": (404, "Bank statement not found"),
    "payments.statement_line_not_found": (404, "Statement line not found"),
    "payments.already_posted": (409, "Payment is already posted"),
    "payments.already_cancelled": (409, "Payment is already cancelled"),
    "payments.not_posted": (409, "Payment has not been posted"),
    "payments.posted_immutable": (409, "Posted payments cannot change"),
    "payments.over_matched": (409, "That would settle more than is open"),
    "payments.residual_mismatch": (409, "Open amounts would stop adding up"),
    "payments.already_reconciled": (409, "Already reconciled"),
    "payments.not_reconciled": (409, "Not reconciled"),
    "payments.default_account_missing": (409, "A company default account is missing"),
    "payments.fx_account_missing": (409, "An exchange gain or loss account is missing"),
    "payments.no_general_journal": (409, "A general journal is needed"),
    "payments.no_bank_journal": (409, "A bank or cash journal is needed"),
    "payments.invalid_amount": (422, "Invalid amount"),
    "payments.invalid_direction": (422, "Invalid payment direction"),
    "payments.invalid_match": (422, "Invalid match"),
    "payments.wrong_journal_type": (422, "A payment needs a bank or cash journal"),
    "payments.wrong_tax_type": (422, "That is not a withholding tax"),
    "payments.wrong_direction": (422, "The payment goes the other way"),
    "payments.amount_mismatch": (422, "The amounts do not agree"),
    "payments.same_side": (422, "A match needs a debit and a credit"),
    "payments.same_line": (422, "A line cannot settle itself"),
    "payments.partner_mismatch": (422, "Those lines belong to different partners"),
    "payments.account_mismatch": (422, "Those lines are on different accounts"),
    "payments.not_reconcilable": (422, "That account keeps no open items"),
    "payments.not_a_bank_account": (422, "That is not a bank or cash account"),
    "payments.unreadable_file": (422, "The statement file could not be read"),
    "payments.unknown_format": (422, "Unknown statement format"),
}

DEFAULT = (409, "Request refused")


def status_and_title(code: str) -> tuple[int, str]:
    return _STATUSES.get(code, DEFAULT)


def problem(code: str, detail: str, *, headers: dict[str, str] | None = None) -> JSONResponse:
    status, title = status_and_title(code)
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
        },
    )


async def domain_error_handler(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, DomainError)
    return problem(error.code, error.message)
