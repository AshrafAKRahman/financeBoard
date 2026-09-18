"""Recording a payment (R1). Drafts only — posting has its own file."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.shared.errors import DomainError
from app.shared.ids import uuid7
from app.treasury.payments import (
    create_payment,
    delete_payment,
    get_payment,
    list_payments,
    update_payment,
)
from tests.factories import TreasuryBooks, make_partner, make_treasury_company
from tests.treasury.conftest import PAYMENT_DATE, draft

pytestmark = pytest.mark.db


class TestRecording:
    def test_a_payment_starts_as_a_draft(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R1.AC1"""
        payment = create_payment(session, books.company_id, draft(books, customer))

        assert payment.state == "draft"
        assert payment.amount == Decimal("1000.00")
        assert payment.number is None
        assert payment.journal_entry_id is None

    def test_money_can_go_either_way(
        self, session: Session, books: TreasuryBooks, customer: UUID, vendor: UUID
    ) -> None:
        """R1.AC2"""
        received = create_payment(session, books.company_id, draft(books, customer))
        paid = create_payment(session, books.company_id, draft(books, vendor, direction="outbound"))

        assert received.is_inbound
        assert not paid.is_inbound

    def test_a_reference_and_a_memo_are_kept(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R1.AC8"""
        payment = create_payment(
            session,
            books.company_id,
            draft(books, customer, reference="SADAD-99821", memo="Part payment, rest in April"),
        )

        assert payment.reference == "SADAD-99821"
        assert payment.memo == "Part payment, rest in April"

    def test_a_cash_journal_is_as_good_as_a_bank_one(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(
            session, books.company_id, draft(books, customer, journal_id=books.journals["CSH"])
        )
        assert payment.journal_id == books.journals["CSH"]

    def test_a_foreign_currency_payment_is_recorded_in_its_own_currency(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(
            session, books.company_id, draft(books, customer, "100.00", currency_code="USD")
        )
        assert (payment.currency_code, payment.amount) == ("USD", Decimal("100.00"))


class TestWhatIsRefused:
    def test_nothing_is_not_a_payment(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R1.AC4"""
        with pytest.raises(DomainError) as caught:
            create_payment(session, books.company_id, draft(books, customer, "0.00"))
        assert caught.value.code == "payments.invalid_amount"

    def test_a_negative_payment_is_refused(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R1.AC4 — money out is a direction, not a negative amount."""
        with pytest.raises(DomainError) as caught:
            create_payment(session, books.company_id, draft(books, customer, "-50.00"))
        assert caught.value.code == "payments.invalid_amount"

    def test_more_decimals_than_the_currency_has_are_refused(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        with pytest.raises(DomainError) as caught:
            create_payment(session, books.company_id, draft(books, customer, "100.005"))
        assert caught.value.code == "payments.invalid_amount"

    def test_a_sales_journal_is_not_a_payment_journal(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R1.AC5"""
        with pytest.raises(DomainError) as caught:
            create_payment(
                session, books.company_id, draft(books, customer, journal_id=books.journals["INV"])
            )
        assert caught.value.code == "payments.wrong_journal_type"

    def test_a_general_journal_is_not_a_payment_journal(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R1.AC5"""
        with pytest.raises(DomainError) as caught:
            create_payment(
                session,
                books.company_id,
                draft(books, customer, journal_id=books.journals["MISC"]),
            )
        assert caught.value.code == "payments.wrong_journal_type"

    def test_another_companys_partner_is_not_found(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R1.AC6 — another company's customer simply does not exist here."""
        other = make_treasury_company(session)
        stranger = make_partner(session, other.company_id, name="Someone Else")

        with pytest.raises(DomainError) as caught:
            create_payment(session, books.company_id, draft(books, stranger.id))
        assert caught.value.code == "payments.partner_not_found"

    def test_an_unknown_partner_is_not_found(self, session: Session, books: TreasuryBooks) -> None:
        with pytest.raises(DomainError) as caught:
            create_payment(session, books.company_id, draft(books, uuid7()))
        assert caught.value.code == "payments.partner_not_found"

    def test_an_unknown_journal_is_not_found(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        with pytest.raises(DomainError) as caught:
            create_payment(session, books.company_id, draft(books, customer, journal_id=uuid7()))
        assert caught.value.code == "payments.journal_not_found"

    def test_a_direction_has_to_be_one_of_the_two(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        with pytest.raises(DomainError) as caught:
            create_payment(session, books.company_id, draft(books, customer, direction="sideways"))
        assert caught.value.code == "payments.invalid_direction"


class TestChangingADraft:
    def test_the_amount_date_partner_and_journal_can_all_change(
        self, session: Session, books: TreasuryBooks, customer: UUID, vendor: UUID
    ) -> None:
        """R1.AC3"""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()

        changed = update_payment(
            session,
            books.company_id,
            payment.id,
            draft(
                books,
                vendor,
                "2500.00",
                direction="outbound",
                date=date(2026, 3, 20),
                journal_id=books.journals["CSH"],
            ),
        )

        assert changed.amount == Decimal("2500.00")
        assert changed.partner_id == vendor
        assert changed.date == date(2026, 3, 20)
        assert changed.journal_id == books.journals["CSH"]
        assert changed.direction == "outbound"

    def test_a_change_is_validated_like_a_new_payment(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()

        with pytest.raises(DomainError) as caught:
            update_payment(session, books.company_id, payment.id, draft(books, customer, "0.00"))
        assert caught.value.code == "payments.invalid_amount"

    def test_a_draft_can_be_deleted(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R1.AC7"""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()

        delete_payment(session, books.company_id, payment.id)

        with pytest.raises(DomainError) as caught:
            get_payment(session, books.company_id, payment.id)
        assert caught.value.code == "payments.payment_not_found"


class TestFindingPayments:
    def test_payments_come_back_newest_first(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R10.AC1"""
        for day in (1, 20, 10):
            create_payment(
                session, books.company_id, draft(books, customer, date=date(2026, 3, day))
            )
        session.flush()

        dates = [payment.date.day for payment in list_payments(session, books.company_id)]
        assert dates == [20, 10, 1]

    def test_they_can_be_narrowed_to_a_partner(
        self, session: Session, books: TreasuryBooks, customer: UUID, vendor: UUID
    ) -> None:
        create_payment(session, books.company_id, draft(books, customer))
        create_payment(session, books.company_id, draft(books, vendor, direction="outbound"))
        session.flush()

        found = list_payments(session, books.company_id, partner_id=vendor)
        assert [payment.partner_id for payment in found] == [vendor]

    def test_they_can_be_narrowed_to_a_direction(
        self, session: Session, books: TreasuryBooks, customer: UUID, vendor: UUID
    ) -> None:
        create_payment(session, books.company_id, draft(books, customer))
        create_payment(session, books.company_id, draft(books, vendor, direction="outbound"))
        session.flush()

        assert len(list_payments(session, books.company_id, direction="inbound")) == 1

    def test_another_companys_payment_is_not_found(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        other = make_treasury_company(session)

        with pytest.raises(DomainError) as caught:
            get_payment(session, other.company_id, payment.id)
        assert caught.value.code == "payments.payment_not_found"

    def test_a_drafts_date_is_kept_as_given(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        assert payment.date == PAYMENT_DATE
