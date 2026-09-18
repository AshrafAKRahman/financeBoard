"""The authorization decision, as a table. No database, no request (R5.AC3, R6.AC2, R6.AC5)."""

import pytest

from app.platform.access.api import Caller, authorize
from app.shared.errors import DomainError
from app.shared.ids import uuid7

RIYADH, JEDDAH, ELSEWHERE = uuid7(), uuid7(), uuid7()


def caller(**permissions: frozenset[str]) -> Caller:
    mapping = {RIYADH: frozenset(), JEDDAH: frozenset()}
    mapping.update({globals()[name.upper()]: codes for name, codes in permissions.items()})
    return Caller(user_id=uuid7(), email="user@example.sa", permissions=mapping)


def test_a_granted_permission_is_allowed() -> None:
    authorize(caller(riyadh=frozenset({"user:invite"})), RIYADH, "user:invite")


def test_a_missing_permission_is_denied() -> None:
    with pytest.raises(DomainError) as error:
        authorize(caller(riyadh=frozenset({"user:read"})), RIYADH, "user:invite")
    assert error.value.code == "identity.permission_denied"
    assert "user:invite" in error.value.message


def test_permissions_do_not_leak_between_companies() -> None:
    """R6.AC5 — the same person may act in one company and not another."""
    subject = caller(riyadh=frozenset({"user:invite"}))
    authorize(subject, RIYADH, "user:invite")
    with pytest.raises(DomainError) as error:
        authorize(subject, JEDDAH, "user:invite")
    assert error.value.code == "identity.permission_denied"


def test_a_company_without_a_role_is_forbidden() -> None:
    with pytest.raises(DomainError) as error:
        authorize(caller(), ELSEWHERE, "user:read")
    assert error.value.code == "identity.company_forbidden"


def test_an_unknown_company_looks_exactly_like_a_forbidden_one() -> None:
    """R6.AC3 — otherwise the API becomes a directory of which companies exist."""
    subject = caller()
    with pytest.raises(DomainError) as unknown:
        authorize(subject, uuid7(), "user:read")
    with pytest.raises(DomainError) as forbidden:
        authorize(subject, ELSEWHERE, "user:read")
    assert str(unknown.value) == str(forbidden.value)


def test_caller_reports_its_companies() -> None:
    subject = caller(riyadh=frozenset({"user:read"}))
    assert subject.companies == {RIYADH, JEDDAH}
    assert subject.may(RIYADH, "user:read")
    assert not subject.may(RIYADH, "user:manage")
    assert not subject.may(ELSEWHERE, "user:read")


def test_nothing_is_allowed_by_default() -> None:
    """R5.AC3 — deny unless granted."""
    empty = Caller(user_id=uuid7(), email="nobody@example.sa")
    assert empty.companies == frozenset()
    with pytest.raises(DomainError):
        authorize(empty, RIYADH, "user:read")
