"""Problem-details responses for domain errors (R2.AC3)."""

import json

import pytest

from app.api.errors import PROBLEM_JSON, problem, status_and_title


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("identity.invalid_credentials", 401),
        ("identity.not_authenticated", 401),
        ("identity.session_expired", 401),
        ("identity.too_many_attempts", 429),
        ("identity.permission_denied", 403),
        ("identity.company_forbidden", 403),
        ("identity.csrf_check_failed", 403),
        ("identity.weak_password", 422),
        ("identity.invitation_expired", 410),
        ("identity.invitation_used", 409),
        ("identity.invitation_email_failed", 502),
        ("audit.append_only", 500),
    ],
)
def test_codes_map_to_their_status(code: str, status: int) -> None:
    assert status_and_title(code)[0] == status


def test_unknown_codes_fall_back_to_conflict() -> None:
    assert status_and_title("ledger.unbalanced") == (409, "Request refused")


def test_response_carries_the_code_and_the_problem_media_type() -> None:
    response = problem("identity.session_expired", "Sign in again to continue.")
    assert response.status_code == 401
    assert response.media_type == PROBLEM_JSON
    body = json.loads(response.body)
    assert body == {
        "type": "about:blank",
        "title": "Session expired",
        "status": 401,
        "code": "identity.session_expired",
        "detail": "Sign in again to continue.",
    }


def test_headers_can_be_attached() -> None:
    response = problem("identity.too_many_attempts", "Try later.", headers={"Retry-After": "900"})
    assert response.headers["Retry-After"] == "900"


def test_titles_never_say_whether_an_account_exists() -> None:
    """R3.AC3 depends on this: one title for every sign-in failure."""
    assert status_and_title("identity.invalid_credentials")[1] == "Sign-in failed"


def test_detail_is_passed_through_verbatim_so_services_control_wording() -> None:
    body = json.loads(problem("identity.invalid_email", "not an address").body)
    assert body["detail"] == "not an address"
