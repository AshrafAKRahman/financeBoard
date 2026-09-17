from dataclasses import dataclass

import pytest
from sqlalchemy.exc import DBAPIError

from app.shared.errors import DomainError, domain_error_from_db


@dataclass
class FakeDiag:
    message_primary: str


class FakeOrig(Exception):
    def __init__(self, primary: str | None) -> None:
        super().__init__(primary or "connection reset")
        if primary is not None:
            self.diag = FakeDiag(primary)


def db_error(primary: str | None) -> DBAPIError:
    return DBAPIError("UPDATE journal_entry …", {}, FakeOrig(primary))


@pytest.mark.parametrize(
    ("primary", "code", "message"),
    [
        (
            "ledger.unbalanced: entry MISC/2026/00001 debit 100.00 credit 99.00",
            "ledger.unbalanced",
            "entry MISC/2026/00001 debit 100.00 credit 99.00",
        ),
        (
            "ledger.posted_immutable: posted entry INV/2026/00007 cannot be updated",
            "ledger.posted_immutable",
            "posted entry INV/2026/00007 cannot be updated",
        ),
        (
            "  ledger.period_locked: entry date 2026-01-31 is on or before lock date 2026-01-31  ",
            "ledger.period_locked",
            "entry date 2026-01-31 is on or before lock date 2026-01-31",
        ),
    ],
)
def test_translates_coded_trigger_errors(primary: str, code: str, message: str) -> None:
    error = domain_error_from_db(db_error(primary))
    assert error is not None
    assert (error.code, error.message) == (code, message)
    assert str(error) == f"{code}: {message}"


def test_multiline_detail_is_kept() -> None:
    error = domain_error_from_db(db_error("ledger.unbalanced: entry off by\n0.01 SAR"))
    assert error is not None
    assert error.message == "entry off by\n0.01 SAR"


@pytest.mark.parametrize(
    "primary",
    [
        'duplicate key value violates unique constraint "journal_entry_number_uniq"',
        "new row for relation \"journal_entry_line\" violates check constraint",
        "ledger_unbalanced: missing the dot",
        "Ledger.Unbalanced: wrong case",
        None,  # no diagnostics at all (e.g. a dropped connection)
    ],
)
def test_leaves_uncoded_errors_alone(primary: str | None) -> None:
    assert domain_error_from_db(db_error(primary)) is None


def test_domain_error_carries_code_and_message() -> None:
    error = DomainError("ledger.rate_missing", "no USD rate on or before 2026-03-01")
    assert error.code == "ledger.rate_missing"
    assert error.message == "no USD rate on or before 2026-03-01"
    assert isinstance(error, Exception)
