"""Cash flow (R4) — the direct method, classified by what the cash was for."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.reporting.cash_flow import FINANCING, INVESTING, OPERATING, UNCLASSIFIED, cash_flow
from app.reporting.periods import Period
from tests.factories import TreasuryBooks
from tests.reporting.conftest import FEBRUARY, JANUARY, MARCH, YEAR, cash_entry

pytestmark = pytest.mark.db


def tag(session: Session, books: TreasuryBooks, code: str, classification: str) -> None:
    session.execute(
        text("UPDATE account SET cash_flow_tag = :t WHERE id = :id"),
        {"t": classification, "id": books.accounts[code]},
    )
    session.flush()


def section(report, classification):
    return next(s for s in report.sections if s.classification == classification)


class TestClassifying:
    def test_cash_from_a_customer_is_operating(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R4.AC1, R4.AC2 — the other side of the entry says what the cash was for."""
        tag(session, books, "1200", OPERATING)
        cash_entry(
            session,
            books,
            on=JANUARY,
            cash_account="1110",
            other_account="1200",
            amount="5000.00",
            cash_in=True,
        )

        report = cash_flow(session, books.company_id, YEAR)
        assert section(report, OPERATING).total == Decimal("5000.00")

    def test_buying_equipment_is_investing(self, session: Session, books: TreasuryBooks) -> None:
        tag(session, books, "5300", INVESTING)
        cash_entry(
            session,
            books,
            on=JANUARY,
            cash_account="1110",
            other_account="5300",
            amount="2000.00",
            cash_in=False,
        )

        report = cash_flow(session, books.company_id, YEAR)
        assert section(report, INVESTING).total == Decimal("-2000.00")

    def test_an_untagged_account_is_operating_but_listed_apart(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R4.AC3 — visible rather than quietly folded in."""
        cash_entry(
            session,
            books,
            on=JANUARY,
            cash_account="1110",
            other_account="4100",
            amount="900.00",
            cash_in=True,
        )

        report = cash_flow(session, books.company_id, YEAR)
        assert section(report, UNCLASSIFIED).total == Decimal("900.00")

    def test_a_loan_is_financing(self, session: Session, books: TreasuryBooks) -> None:
        tag(session, books, "2300", FINANCING)
        cash_entry(
            session,
            books,
            on=JANUARY,
            cash_account="1110",
            other_account="2300",
            amount="10000.00",
            cash_in=True,
        )

        report = cash_flow(session, books.company_id, YEAR)
        assert section(report, FINANCING).total == Decimal("10000.00")


class TestItReconciles:
    def test_opening_plus_movement_equals_closing(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R4.AC5 — the identity that makes the statement worth reading."""
        tag(session, books, "1200", OPERATING)
        cash_entry(
            session,
            books,
            on=JANUARY,
            cash_account="1110",
            other_account="1200",
            amount="5000.00",
            cash_in=True,
        )
        cash_entry(
            session,
            books,
            on=FEBRUARY,
            cash_account="1110",
            other_account="5300",
            amount="1200.00",
            cash_in=False,
        )

        report = cash_flow(session, books.company_id, YEAR)

        assert report.reconciles
        assert report.net_movement == Decimal("3800.00")
        assert report.closing_cash == Decimal("3800.00")

    def test_an_earlier_period_becomes_opening_cash(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R4.AC4"""
        cash_entry(
            session,
            books,
            on=JANUARY,
            cash_account="1110",
            other_account="4100",
            amount="5000.00",
            cash_in=True,
        )
        cash_entry(
            session,
            books,
            on=MARCH,
            cash_account="1110",
            other_account="4100",
            amount="1000.00",
            cash_in=True,
        )

        march = Period(date(2026, 3, 1), date(2026, 3, 31), "March")
        report = cash_flow(session, books.company_id, march)

        assert report.opening_cash == Decimal("5000.00")
        assert report.net_movement == Decimal("1000.00")
        assert report.closing_cash == Decimal("6000.00")

    def test_one_payment_covering_two_things_splits_itself(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R4.AC5, and why no allocation is needed: the counterparts already sum to the cash."""
        from app.ledger.api import PostingLine, PostingRequest, post

        tag(session, books, "5300", OPERATING)
        tag(session, books, "5800", INVESTING)
        post(
            session,
            PostingRequest(
                company_id=books.company_id,
                journal_id=books.journals["MISC"],
                date=JANUARY,
                currency_code="SAR",
                lines=[
                    PostingLine(books.accounts["5300"], debit=Decimal("300.00")),
                    PostingLine(books.accounts["5800"], debit=Decimal("700.00")),
                    PostingLine(books.accounts["1110"], credit=Decimal("1000.00")),
                ],
            ),
        )
        session.flush()

        report = cash_flow(session, books.company_id, YEAR)

        assert section(report, OPERATING).total == Decimal("-300.00")
        assert section(report, INVESTING).total == Decimal("-700.00")
        assert report.net_movement == Decimal("-1000.00")
        assert report.reconciles

    def test_moving_money_between_your_own_accounts_is_not_a_cash_flow(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """Both sides are cash, so there are no counterpart lines and nothing to report."""
        from app.ledger.api import PostingLine, PostingRequest, post

        cash_entry(
            session,
            books,
            on=JANUARY,
            cash_account="1110",
            other_account="4100",
            amount="5000.00",
            cash_in=True,
        )
        post(
            session,
            PostingRequest(
                company_id=books.company_id,
                journal_id=books.journals["MISC"],
                date=FEBRUARY,
                currency_code="SAR",
                lines=[
                    PostingLine(books.accounts["1115"], debit=Decimal("2000.00")),
                    PostingLine(books.accounts["1110"], credit=Decimal("2000.00")),
                ],
            ),
        )
        session.flush()

        report = cash_flow(session, books.company_id, YEAR)

        assert report.net_movement == Decimal("5000.00")
        assert report.reconciles


def test_the_method_is_direct(session: Session, books: TreasuryBooks) -> None:
    """R4.AC6 — built from cash movements, never from the net result adjusted."""
    cash_entry(
        session,
        books,
        on=JANUARY,
        cash_account="1110",
        other_account="4100",
        amount="5000.00",
        cash_in=True,
    )

    report = cash_flow(session, books.company_id, YEAR)
    lines = [line for s in report.sections for line in s.lines]

    assert any(line.code == "4100" for line in lines)
