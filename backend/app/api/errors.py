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
