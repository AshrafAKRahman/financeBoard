"""`post()` end to end against PostgreSQL: the posted entry, its number, currency
conversion, caller-owned transactions and error translation.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.db import transaction
from app.ledger.api import JournalEntry, PostingLine, PostingRequest, post
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from tests.factories import Books, add_rate, make_books

pytestmark = pytest.mark.db

ENTRY_DATE = date(2026, 3, 1)


def sale(books: Books, amount: str, *, currency: str = "SAR", **kwargs) -> PostingRequest:
    """Debit the customer, credit revenue — the shape invoicing will post."""
    return PostingRequest(
        company_id=books.company_id,
        journal_id=books.journals["INV"],
        date=ENTRY_DATE,
        currency_code=currency,
        lines=(
            PostingLine(books.accounts["receivable"], debit=Decimal(amount), name="Customer"),
            PostingLine(books.accounts["revenue"], credit=Decimal(amount), name="Revenue"),
        ),
        **kwargs,
    )


def test_posts_a_balanced_entry_with_its_lines(session: Session) -> None:
    books = make_books(session)
    entry = post(session, sale(books, "1150.00", ref="INV-1"))
    session.commit()

    assert entry.state == "posted"
    assert entry.posted_at is not None
    assert entry.ref == "INV-1"
    assert entry.currency_code == "SAR"
    assert [
        (line.line_no, line.debit, line.credit, line.amount_currency) for line in entry.lines
    ] == [
        (1, Decimal("1150.00"), Decimal(0), Decimal("1150.00")),
        (2, Decimal(0), Decimal("1150.00"), Decimal("-1150.00")),
    ]
    assert sum(line.debit for line in entry.lines) == sum(line.credit for line in entry.lines)


def test_numbers_entries_per_journal_and_fiscal_year(session: Session) -> None:
    books = make_books(session)
    first = post(session, sale(books, "100.00"))
    second = post(session, sale(books, "200.00"))
    session.commit()

    assert (first.number, second.number) == ("INV/2026/00001", "INV/2026/00002")

    other_journal = PostingRequest(
        company_id=books.company_id,
        journal_id=books.journals["MISC"],
        date=ENTRY_DATE,
        currency_code="SAR",
        lines=(
            PostingLine(books.accounts["expense"], debit=Decimal("50.00")),
            PostingLine(books.accounts["bank"], credit=Decimal("50.00")),
        ),
    )
    assert post(session, other_journal).number == "MISC/2026/00001"
    session.commit()


def test_fiscal_year_follows_the_company_setting(session: Session) -> None:
    """A fiscal year starting in April puts March 2026 in fiscal year 2025."""
    books = make_books(session, fiscal_year_start_month=4)
    march = post(session, sale(books, "100.00"))
    session.commit()
    assert march.number == "INV/2025/00001"

    april = post(session, sale(books, "100.00"))
    april_entry = post(
        session,
        PostingRequest(
            company_id=books.company_id,
            journal_id=books.journals["INV"],
            date=date(2026, 4, 1),
            currency_code="SAR",
            lines=(
                PostingLine(books.accounts["receivable"], debit=Decimal("10.00")),
                PostingLine(books.accounts["revenue"], credit=Decimal("10.00")),
            ),
        ),
    )
    session.commit()
    assert april.number == "INV/2025/00002"
    assert april_entry.number == "INV/2026/00001"


def test_stores_both_currency_amounts_for_a_foreign_entry(session: Session) -> None:
    books = make_books(session)
    add_rate(session, books, "USD", date(2026, 1, 1), "3.7500")

    entry = post(session, sale(books, "100.00", currency="USD"))
    session.commit()

    assert entry.currency_code == "USD"
    assert [(line.debit, line.credit, line.amount_currency) for line in entry.lines] == [
        (Decimal("375.00"), Decimal(0), Decimal("100.00")),
        (Decimal(0), Decimal("375.00"), Decimal("-100.00")),
    ]


def test_adds_a_rounding_line_when_conversion_does_not_balance(session: Session) -> None:
    books = make_books(session)
    add_rate(session, books, "USD", date(2026, 1, 1), "3.755")

    entry = post(
        session,
        PostingRequest(
            company_id=books.company_id,
            journal_id=books.journals["INV"],
            date=ENTRY_DATE,
            currency_code="USD",
            lines=(
                PostingLine(books.accounts["receivable"], debit=Decimal("0.03")),
                PostingLine(books.accounts["revenue"], credit=Decimal("0.01")),
                PostingLine(books.accounts["revenue"], credit=Decimal("0.01")),
                PostingLine(books.accounts["revenue"], credit=Decimal("0.01")),
            ),
        ),
    )
    session.commit()

    rounding = entry.lines[-1]
    assert rounding.account_id == books.accounts["rounding"]
    assert rounding.amount_currency == 0
    assert sum(line.debit for line in entry.lines) == sum(line.credit for line in entry.lines)
    assert sum(line.amount_currency for line in entry.lines) == 0


def test_posting_without_a_rate_is_refused(session: Session) -> None:
    books = make_books(session)
    with pytest.raises(DomainError) as error:
        post(session, sale(books, "100.00", currency="USD"))
    assert error.value.code == "ledger.rate_missing"


def test_caller_owns_the_transaction(session: Session, engine: Engine) -> None:
    """R2.AC3 — nothing is visible to other sessions until the caller commits."""
    books = make_books(session)
    entry = post(session, sale(books, "500.00"))

    with Session(engine) as other:
        assert other.get(JournalEntry, entry.id) is None

    session.commit()

    with Session(engine) as other:
        assert other.get(JournalEntry, entry.id) is not None


def test_rollback_leaves_no_entry_and_no_number_gap(session: Session) -> None:
    books = make_books(session)
    post(session, sale(books, "100.00"))
    session.rollback()

    entry = post(session, sale(books, "100.00"))
    session.commit()
    assert entry.number == "INV/2026/00001"


def replacing(request: PostingRequest, **changes) -> PostingRequest:
    fields = {field: getattr(request, field) for field in request.__slots__}
    return PostingRequest(**{**fields, **changes})


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"company_id": uuid7()}, "ledger.company_not_found"),
        ({"journal_id": uuid7()}, "ledger.journal_not_found"),
    ],
)
def test_unknown_company_or_journal_is_refused(session: Session, change: dict, code: str) -> None:
    books = make_books(session)
    with pytest.raises(DomainError) as error:
        post(session, replacing(sale(books, "100.00"), **change))
    assert error.value.code == code


def test_journal_of_another_company_is_refused(session: Session) -> None:
    ours = make_books(session)
    theirs = make_books(session)
    request = PostingRequest(
        company_id=ours.company_id,
        journal_id=theirs.journals["INV"],
        date=ENTRY_DATE,
        currency_code="SAR",
        lines=(
            PostingLine(ours.accounts["receivable"], debit=Decimal("10.00")),
            PostingLine(ours.accounts["revenue"], credit=Decimal("10.00")),
        ),
    )
    with pytest.raises(DomainError) as error:
        post(session, request)
    assert error.value.code == "ledger.journal_not_found"


def test_archived_journal_is_refused(session: Session) -> None:
    books = make_books(session)
    session.execute(
        text("UPDATE journal SET active = false WHERE id = :id"), {"id": books.journals["INV"]}
    )
    session.commit()

    with pytest.raises(DomainError) as error:
        post(session, sale(books, "100.00"))
    assert error.value.code == "ledger.journal_inactive"


def test_trigger_errors_during_posting_become_domain_errors(session: Session) -> None:
    """R13.AC1 — a group-account line is refused by the line trigger, not by Python."""
    books = make_books(session)
    request = PostingRequest(
        company_id=books.company_id,
        journal_id=books.journals["MISC"],
        date=ENTRY_DATE,
        currency_code="SAR",
        lines=(
            PostingLine(books.accounts["current_assets"], debit=Decimal("10.00")),
            PostingLine(books.accounts["revenue"], credit=Decimal("10.00")),
        ),
    )
    with pytest.raises(DomainError) as error:
        post(session, request)
    assert error.value.code == "ledger.group_account"
    session.rollback()


def test_deferred_balance_error_at_commit_becomes_a_domain_error(
    session: Session, engine: Engine
) -> None:
    """R13.AC2 — the unit of work translates the commit-time check too.

    Raw SQL builds a posted entry that does not balance; nothing complains until COMMIT,
    when the deferred trigger fires and the whole transaction is rolled back.
    """
    books = make_books(session)
    entry_id = uuid7()

    def write_unbalanced_entry(unit: Session) -> None:
        unit.execute(
            text(
                "INSERT INTO journal_entry (id, company_id, journal_id, date, currency_code) "
                "VALUES (:id, :company, :journal, :date, 'SAR')"
            ),
            {
                "id": entry_id,
                "company": books.company_id,
                "journal": books.journals["MISC"],
                "date": ENTRY_DATE,
            },
        )
        for line_no, (account, debit, credit) in enumerate(
            [("expense", "100.00", "0"), ("bank", "0", "99.00")], start=1
        ):
            unit.execute(
                text(
                    "INSERT INTO journal_entry_line (id, entry_id, company_id, line_no, "
                    "account_id, debit, credit, currency_code, amount_currency) VALUES "
                    "(:id, :entry, :company, :no, :account, :debit, :credit, 'SAR', :amount)"
                ),
                {
                    "id": uuid7(),
                    "entry": entry_id,
                    "company": books.company_id,
                    "no": line_no,
                    "account": books.accounts[account],
                    "debit": debit,
                    "credit": credit,
                    "amount": str(Decimal(debit) - Decimal(credit)),
                },
            )
        unit.execute(
            text(
                "UPDATE journal_entry SET state = 'posted', number = 'MISC/2026/09999', "
                "posted_at = now() WHERE id = :id"
            ),
            {"id": entry_id},
        )

    with pytest.raises(DomainError) as error, transaction(engine) as unit:
        write_unbalanced_entry(unit)

    assert error.value.code == "ledger.unbalanced"

    with Session(engine) as check:
        assert check.get(JournalEntry, entry_id) is None


def test_source_document_is_recorded(session: Session) -> None:
    books = make_books(session)
    invoice_id = uuid7()
    entry = post(session, sale(books, "230.00", source_type="invoice", source_id=invoice_id))
    session.commit()

    assert (entry.source_type, entry.source_id) == ("invoice", invoice_id)
    found = session.execute(
        select(JournalEntry.id).where(
            JournalEntry.source_type == "invoice", JournalEntry.source_id == invoice_id
        )
    ).scalar_one()
    assert found == entry.id
