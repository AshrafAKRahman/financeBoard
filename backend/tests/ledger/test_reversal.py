"""`reverse()` — the only way to correct a posted entry (R5)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.ledger.api import JournalEntry, PostingLine, PostingRequest, post, reverse
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from tests.factories import Books, add_rate, make_books

pytestmark = pytest.mark.db

ENTRY_DATE = date(2026, 3, 1)


def sale(books: Books, amount: str = "1150.00", *, currency: str = "SAR") -> PostingRequest:
    return PostingRequest(
        company_id=books.company_id,
        journal_id=books.journals["INV"],
        date=ENTRY_DATE,
        currency_code=currency,
        lines=(
            PostingLine(
                books.accounts["receivable"],
                debit=Decimal(amount),
                name="Customer",
                due_date=date(2026, 4, 1),
            ),
            PostingLine(books.accounts["revenue"], credit=Decimal(amount), name="Revenue"),
        ),
    )


def test_reversal_swaps_every_line_and_links_back(session: Session) -> None:
    books = make_books(session)
    original = post(session, sale(books))
    session.commit()

    reversal = reverse(session, books.company_id, original.id)
    session.commit()

    assert reversal.state == "posted"
    assert reversal.reversed_entry_id == original.id
    assert reversal.number == "INV/2026/00002"
    assert reversal.ref == f"Reversal of {original.number}"
    assert [(line.debit, line.credit, line.amount_currency) for line in reversal.lines] == [
        (Decimal(0), Decimal("1150.00"), Decimal("-1150.00")),
        (Decimal("1150.00"), Decimal(0), Decimal("1150.00")),
    ]
    assert [line.account_id for line in reversal.lines] == [
        line.account_id for line in original.lines
    ]
    assert [line.name for line in reversal.lines] == ["Customer", "Revenue"]
    assert reversal.lines[0].due_date == date(2026, 4, 1)


def test_the_pair_nets_to_zero_per_account(session: Session) -> None:
    books = make_books(session)
    original = post(session, sale(books))
    session.commit()
    reverse(session, books.company_id, original.id)
    session.commit()

    balances = session.execute(
        text(
            """
            SELECT account_id, sum(debit) - sum(credit) AS balance, sum(amount_currency) AS amount
            FROM journal_entry_line WHERE company_id = :company GROUP BY account_id
            """
        ),
        {"company": books.company_id},
    ).all()
    assert balances, "expected posted lines"
    assert all(row.balance == 0 and row.amount == 0 for row in balances)


def test_foreign_currency_reversal_copies_company_amounts(session: Session) -> None:
    """Company amounts are copied, never re-converted, so a later rate cannot leave a
    residue behind — including the rounding line."""
    books = make_books(session)
    add_rate(session, books, "USD", date(2026, 1, 1), "3.755")

    original = post(
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
    assert len(original.lines) == 5  # four requested plus the rounding line

    # A different rate later must not change the reversal.
    add_rate(session, books, "USD", date(2026, 4, 1), "3.9000")
    reversal = reverse(session, books.company_id, original.id, on=date(2026, 5, 1))
    session.commit()

    assert len(reversal.lines) == len(original.lines)
    assert sum(line.debit for line in reversal.lines) == sum(line.credit for line in original.lines)
    total = session.execute(
        text(
            "SELECT sum(debit) - sum(credit), sum(amount_currency) "
            "FROM journal_entry_line WHERE company_id = :c"
        ),
        {"c": books.company_id},
    ).one()
    assert total == (0, 0)


def test_reversal_date_defaults_to_the_original(session: Session) -> None:
    books = make_books(session)
    original = post(session, sale(books))
    session.commit()

    reversal = reverse(session, books.company_id, original.id)
    session.commit()
    assert reversal.date == original.date == ENTRY_DATE


def test_reversal_can_be_dated_later(session: Session) -> None:
    books = make_books(session)
    original = post(session, sale(books))
    session.commit()

    reversal = reverse(
        session, books.company_id, original.id, on=date(2026, 4, 15), ref="Customer cancelled"
    )
    session.commit()
    assert reversal.date == date(2026, 4, 15)
    assert reversal.ref == "Customer cancelled"


def test_a_draft_entry_cannot_be_reversed(session: Session, engine: Engine) -> None:
    books = make_books(session)
    draft_id = uuid7()
    session.execute(
        text(
            "INSERT INTO journal_entry (id, company_id, journal_id, date, currency_code) "
            "VALUES (:id, :company, :journal, :date, 'SAR')"
        ),
        {
            "id": draft_id,
            "company": books.company_id,
            "journal": books.journals["MISC"],
            "date": ENTRY_DATE,
        },
    )
    session.commit()

    with pytest.raises(DomainError) as error:
        reverse(session, books.company_id, draft_id)
    assert error.value.code == "ledger.reverse_unposted"


def test_an_entry_can_only_be_reversed_once(session: Session) -> None:
    books = make_books(session)
    original = post(session, sale(books))
    session.commit()
    first = reverse(session, books.company_id, original.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        reverse(session, books.company_id, original.id)
    assert error.value.code == "ledger.already_reversed"
    assert first.number in error.value.message
    session.rollback()


def test_a_reversal_can_itself_be_reversed(session: Session) -> None:
    """Re-posting after a correction is a new reversal of the reversal, not an edit."""
    books = make_books(session)
    original = post(session, sale(books))
    session.commit()
    reversal = reverse(session, books.company_id, original.id)
    session.commit()

    second = reverse(session, books.company_id, reversal.id)
    session.commit()
    assert second.reversed_entry_id == reversal.id
    assert [(line.debit, line.credit) for line in second.lines] == [
        (line.debit, line.credit) for line in original.lines
    ]


def test_unknown_entry_or_wrong_company_is_refused(session: Session) -> None:
    ours = make_books(session)
    theirs = make_books(session)
    theirs_entry = post(session, sale(theirs))
    session.commit()

    with pytest.raises(DomainError) as missing:
        reverse(session, ours.company_id, uuid7())
    assert missing.value.code == "ledger.entry_not_found"

    with pytest.raises(DomainError) as other_company:
        reverse(session, ours.company_id, theirs_entry.id)
    assert other_company.value.code == "ledger.entry_not_found"


def test_the_original_entry_is_untouched(session: Session, engine: Engine) -> None:
    books = make_books(session)
    original = post(session, sale(books))
    session.commit()
    before = session.execute(
        text("SELECT number, state, updated_at FROM journal_entry WHERE id = :id"),
        {"id": original.id},
    ).one()

    reverse(session, books.company_id, original.id)
    session.commit()

    after = session.execute(
        text("SELECT number, state, updated_at FROM journal_entry WHERE id = :id"),
        {"id": original.id},
    ).one()
    assert before == after

    with Session(engine) as other:
        entry = other.get(JournalEntry, original.id)
        assert entry is not None and entry.reversed_entry_id is None
