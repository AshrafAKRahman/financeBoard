"""Payments, matching and reconciliation over HTTP (R10)."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.platform.access.api import grant_role, set_role_permissions
from app.platform.access.models import ADMINISTRATOR_ROLE_ID, Role
from app.shared.ids import uuid7
from tests.api.conftest import SAME_ORIGIN, Person, sign_in
from tests.factories import TreasuryBooks, make_partner, make_treasury_company

pytestmark = pytest.mark.db

PAYMENT_DATE = "2026-03-15"
INVOICE_DATE = "2026-03-01"


@pytest.fixture
def books(session: Session, administrator: Person) -> TreasuryBooks:
    treasury = make_treasury_company(session)
    grant_role(
        session,
        user_id=administrator.user_id,
        company_id=treasury.company_id,
        role_id=ADMINISTRATOR_ROLE_ID,
    )
    session.commit()
    return treasury


@pytest.fixture
def base(client: TestClient, administrator: Person, books: TreasuryBooks) -> str:
    sign_in(client, administrator)
    return f"/api/v1/companies/{books.company_id}"


@pytest.fixture
def customer(session: Session, books: TreasuryBooks) -> str:
    return str(make_partner(session, books.company_id, name="Al Noor Est", type="customer").id)


def payment_body(books: TreasuryBooks, customer: str, **overrides) -> dict:
    body = {
        "direction": "inbound",
        "partner_id": customer,
        "journal_id": str(books.journals["BNK"]),
        "date": PAYMENT_DATE,
        "amount": "1000.00",
        "currency_code": "SAR",
    }
    body.update(overrides)
    return body


def invoice_body(books: TreasuryBooks, customer: str, amount: str = "1000.00") -> dict:
    return {
        "type": "out_invoice",
        "partner_id": customer,
        "journal_id": str(books.journals["INV"]),
        "date": INVOICE_DATE,
        "currency_code": "SAR",
        "lines": [
            {
                "description": "Consultancy",
                "quantity": "1",
                "unit_price": amount,
                "account_id": str(books.accounts["4100"]),
            }
        ],
    }


def post_invoice(client: TestClient, base: str, books: TreasuryBooks, customer: str, amount: str):
    created = client.post(
        f"{base}/documents", json=invoice_body(books, customer, amount), headers=SAME_ORIGIN
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    issued = client.post(f"{base}/documents/{document_id}/post", headers=SAME_ORIGIN)
    assert issued.status_code == 200, issued.text
    return document_id


def post_payment(client: TestClient, base: str, books: TreasuryBooks, customer: str, **overrides):
    created = client.post(
        f"{base}/payments", json=payment_body(books, customer, **overrides), headers=SAME_ORIGIN
    )
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]
    posted = client.post(f"{base}/payments/{payment_id}/post", headers=SAME_ORIGIN)
    assert posted.status_code == 200, posted.text
    return posted.json()


class TestRecordingAPayment:
    def test_a_payment_can_be_created(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC2"""
        response = client.post(
            f"{base}/payments", json=payment_body(books, customer), headers=SAME_ORIGIN
        )

        assert response.status_code == 201, response.text
        assert response.json()["state"] == "draft"
        assert response.json()["amount"] == "1000.00"

    def test_a_draft_can_be_changed_and_deleted(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC2"""
        created = client.post(
            f"{base}/payments", json=payment_body(books, customer), headers=SAME_ORIGIN
        )
        payment_id = created.json()["id"]

        changed = client.patch(
            f"{base}/payments/{payment_id}",
            json=payment_body(books, customer, amount="250.00"),
            headers=SAME_ORIGIN,
        )
        assert changed.status_code == 200
        assert changed.json()["amount"] == "250.00"

        removed = client.delete(f"{base}/payments/{payment_id}", headers=SAME_ORIGIN)
        assert removed.status_code == 204
        assert client.get(f"{base}/payments/{payment_id}").status_code == 404

    def test_payments_are_listed_newest_first(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC1"""
        for day in ("2026-03-01", "2026-03-20", "2026-03-10"):
            client.post(
                f"{base}/payments",
                json=payment_body(books, customer, date=day),
                headers=SAME_ORIGIN,
            )

        listed = client.get(f"{base}/payments")
        assert [row["date"] for row in listed.json()] == [
            "2026-03-20",
            "2026-03-10",
            "2026-03-01",
        ]

    def test_a_bad_amount_is_a_422_with_a_code(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """NFR5"""
        response = client.post(
            f"{base}/payments",
            json=payment_body(books, customer, amount="0.00"),
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 422
        assert response.json()["code"] == "payments.invalid_amount"

    def test_the_wrong_journal_is_a_422_with_a_code(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        response = client.post(
            f"{base}/payments",
            json=payment_body(books, customer, journal_id=str(books.journals["INV"])),
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 422
        assert response.json()["code"] == "payments.wrong_journal_type"


class TestPostingAndCancelling:
    def test_a_payment_can_be_posted(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC3"""
        posted = post_payment(client, base, books, customer)

        assert posted["state"] == "posted"
        assert posted["number"].startswith("BNK/2026/")

    def test_posting_twice_is_a_409(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        posted = post_payment(client, base, books, customer)

        again = client.post(f"{base}/payments/{posted['id']}/post", headers=SAME_ORIGIN)
        assert again.status_code == 409
        assert again.json()["code"] == "payments.already_posted"

    def test_a_payment_can_be_cancelled_with_a_reason(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC3"""
        posted = post_payment(client, base, books, customer)

        cancelled = client.post(
            f"{base}/payments/{posted['id']}/cancel",
            json={"reason": "wrong customer"},
            headers=SAME_ORIGIN,
        )

        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"
        assert cancelled.json()["cancel_reason"] == "wrong customer"

    def test_changing_a_posted_payment_is_a_409(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        posted = post_payment(client, base, books, customer)

        response = client.patch(
            f"{base}/payments/{posted['id']}",
            json=payment_body(books, customer, amount="5.00"),
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 409
        assert response.json()["code"] == "payments.posted_immutable"


class TestMatching:
    def test_open_items_are_listed(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        post_invoice(client, base, books, customer, "1000.00")

        items = client.get(f"{base}/open-items", params={"partner_id": customer})

        assert items.status_code == 200
        assert [row["open_amount"] for row in items.json()] == ["1000.000000"]
        assert items.json()[0]["is_debit"] is True

    def test_a_pair_of_lines_can_be_matched(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC4"""
        post_invoice(client, base, books, customer, "1000.00")
        post_payment(client, base, books, customer)
        items = client.get(f"{base}/open-items", params={"partner_id": customer}).json()
        debit = next(row["line_id"] for row in items if row["is_debit"])
        credit = next(row["line_id"] for row in items if not row["is_debit"])

        matched = client.post(
            f"{base}/reconciliations",
            json={"debit_line_id": debit, "credit_line_id": credit},
            headers=SAME_ORIGIN,
        )

        assert matched.status_code == 201, matched.text
        assert matched.json()[0]["debit_amount"] == "1000.000000"
        assert client.get(f"{base}/open-items", params={"partner_id": customer}).json() == []

    def test_a_set_of_lines_can_be_matched(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC4"""
        post_invoice(client, base, books, customer, "400.00")
        post_invoice(client, base, books, customer, "600.00")
        post_payment(client, base, books, customer)
        line_ids = [
            row["line_id"]
            for row in client.get(f"{base}/open-items", params={"partner_id": customer}).json()
        ]

        matched = client.post(
            f"{base}/reconciliations", json={"line_ids": line_ids}, headers=SAME_ORIGIN
        )

        assert matched.status_code == 201, matched.text
        assert len(matched.json()) == 2

    def test_a_match_can_be_undone(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC4"""
        post_invoice(client, base, books, customer, "1000.00")
        post_payment(client, base, books, customer)
        items = client.get(f"{base}/open-items", params={"partner_id": customer}).json()
        matched = client.post(
            f"{base}/reconciliations",
            json={
                "debit_line_id": next(r["line_id"] for r in items if r["is_debit"]),
                "credit_line_id": next(r["line_id"] for r in items if not r["is_debit"]),
            },
            headers=SAME_ORIGIN,
        ).json()

        undone = client.delete(f"{base}/reconciliations/{matched[0]['id']}", headers=SAME_ORIGIN)

        assert undone.status_code == 204
        assert len(client.get(f"{base}/open-items", params={"partner_id": customer}).json()) == 2

    def test_over_matching_is_a_409_with_a_code(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """NFR5"""
        post_invoice(client, base, books, customer, "1000.00")
        post_payment(client, base, books, customer, amount="2000.00")
        items = client.get(f"{base}/open-items", params={"partner_id": customer}).json()

        response = client.post(
            f"{base}/reconciliations",
            json={
                "debit_line_id": next(r["line_id"] for r in items if r["is_debit"]),
                "credit_line_id": next(r["line_id"] for r in items if not r["is_debit"]),
                "amount": "1500.00",
            },
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 409
        assert response.json()["code"] == "payments.over_matched"

    def test_suggestions_are_offered_for_a_payment(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        post_invoice(client, base, books, customer, "1000.00")
        posted = post_payment(client, base, books, customer)

        suggestions = client.get(f"{base}/payments/{posted['id']}/suggestions")

        assert suggestions.status_code == 200
        assert suggestions.json()[0]["reason"] == "the amount matches exactly"


class TestTheDocumentsPaymentState:
    def test_an_invoice_reports_its_state_and_its_payments(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC8"""
        document_id = post_invoice(client, base, books, customer, "1000.00")
        posted = post_payment(client, base, books, customer)
        items = client.get(f"{base}/open-items", params={"partner_id": customer}).json()
        client.post(
            f"{base}/reconciliations",
            json={
                "debit_line_id": next(r["line_id"] for r in items if r["is_debit"]),
                "credit_line_id": next(r["line_id"] for r in items if not r["is_debit"]),
            },
            headers=SAME_ORIGIN,
        )

        state = client.get(f"{base}/documents/{document_id}/payment-state")

        assert state.status_code == 200
        body = state.json()
        assert body["state"] == "paid"
        assert body["payments"][0]["number"] == posted["number"]

    def test_an_unpaid_invoice_says_not_paid(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        document_id = post_invoice(client, base, books, customer, "1000.00")

        state = client.get(f"{base}/documents/{document_id}/payment-state")
        assert state.json()["state"] == "not_paid"


class TestStatements:
    csv = b"Date,Amount,Narrative,Ref\n2026-03-15,1000.00,Receipt,TRX-1\n"

    def upload(
        self, client: TestClient, base: str, books: TreasuryBooks, payload: bytes | None = None
    ):
        return client.post(
            f"{base}/bank-statements/import",
            data={
                "bank_account_id": str(books.accounts["1110"]),
                "source_format": "csv",
                "mapping": json.dumps(
                    {
                        "date": "Date",
                        "amount": "Amount",
                        "description": "Narrative",
                        "reference": "Ref",
                    }
                ),
            },
            files={"file": ("march.csv", payload or self.csv, "text/csv")},
            headers=SAME_ORIGIN,
        )

    def test_a_statement_can_be_imported(
        self, client: TestClient, base: str, books: TreasuryBooks
    ) -> None:
        """R10.AC5"""
        response = self.upload(client, base, books)

        assert response.status_code == 201, response.text
        assert response.json()["created"] == 1
        assert response.json()["duplicates"] == 0

    def test_the_same_file_twice_reports_duplicates(
        self, client: TestClient, base: str, books: TreasuryBooks
    ) -> None:
        self.upload(client, base, books)
        again = self.upload(client, base, books)

        assert again.json() == {
            **again.json(),
            "created": 0,
            "duplicates": 1,
        }

    def test_an_unreadable_file_is_a_422_with_a_code(
        self, client: TestClient, base: str, books: TreasuryBooks
    ) -> None:
        response = self.upload(client, base, books, payload=b"   ")

        assert response.status_code == 422
        assert response.json()["code"] == "payments.unreadable_file"

    def test_the_statement_and_its_lines_can_be_read_back(
        self, client: TestClient, base: str, books: TreasuryBooks
    ) -> None:
        statement_id = self.upload(client, base, books).json()["statement_id"]

        statements = client.get(f"{base}/bank-statements")
        lines = client.get(f"{base}/bank-statements/{statement_id}/lines")

        assert [row["id"] for row in statements.json()] == [statement_id]
        assert lines.json()[0]["bank_reference"] == "TRX-1"
        assert lines.json()[0]["reconciled"] is False

    def test_a_line_can_be_reconciled_and_undone(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        """R10.AC4 — the entry that finally moves the bank account."""
        posted = post_payment(client, base, books, customer)
        statement_id = self.upload(client, base, books).json()["statement_id"]
        line_id = client.get(f"{base}/bank-statements/{statement_id}/lines").json()[0]["id"]

        reconciled = client.post(
            f"{base}/bank-statement-lines/{line_id}/reconcile",
            json={"payment_id": posted["id"]},
            headers=SAME_ORIGIN,
        )
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["reconciled"] is True

        undone = client.post(f"{base}/bank-statement-lines/{line_id}/undo", headers=SAME_ORIGIN)
        assert undone.json()["reconciled"] is False

    def test_suggestions_are_offered_for_a_statement_line(
        self, client: TestClient, base: str, books: TreasuryBooks, customer: str
    ) -> None:
        posted = post_payment(client, base, books, customer)
        statement_id = self.upload(client, base, books).json()["statement_id"]
        line_id = client.get(f"{base}/bank-statements/{statement_id}/lines").json()[0]["id"]

        suggestions = client.get(f"{base}/bank-statement-lines/{line_id}/suggestions")

        assert [row["payment_id"] for row in suggestions.json()] == [posted["id"]]

    def test_unreconciled_lines_are_listed(
        self, client: TestClient, base: str, books: TreasuryBooks
    ) -> None:
        self.upload(client, base, books)

        lines = client.get(f"{base}/bank-statement-lines")
        assert len(lines.json()) == 1


class TestPermissions:
    @pytest.fixture
    def reader(self, session: Session, books: TreasuryBooks, mailer, client: TestClient):
        """Someone who may look at payments but not touch them (R10.AC6)."""
        from tests.api.conftest import make_person

        person = make_person(session, mailer, name="Reader")
        role = Role(id=uuid7(), name=f"Payments reader {uuid7().hex[-6:]}")
        session.add(role)
        session.flush()
        set_role_permissions(session, role.id, ["payment:read", "invoice:read"])
        grant_role(session, user_id=person.user_id, company_id=books.company_id, role_id=role.id)
        session.commit()
        sign_in(client, person)
        return person

    def test_a_reader_may_list_payments(
        self, client: TestClient, books: TreasuryBooks, reader
    ) -> None:
        response = client.get(f"/api/v1/companies/{books.company_id}/payments")
        assert response.status_code == 200

    def test_a_reader_may_not_create_one(
        self, client: TestClient, books: TreasuryBooks, customer: str, reader
    ) -> None:
        """R10.AC6"""
        response = client.post(
            f"/api/v1/companies/{books.company_id}/payments",
            json=payment_body(books, customer),
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 403

    def test_a_reader_may_not_match(self, client: TestClient, books: TreasuryBooks, reader) -> None:
        """R10.AC6"""
        response = client.post(
            f"/api/v1/companies/{books.company_id}/reconciliations",
            json={"line_ids": [str(uuid7()), str(uuid7())]},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 403

    def test_a_reader_may_not_import_a_statement(
        self, client: TestClient, books: TreasuryBooks, reader
    ) -> None:
        """R10.AC6 — importing has its own permission."""
        response = client.post(
            f"/api/v1/companies/{books.company_id}/bank-statements/import",
            data={
                "bank_account_id": str(books.accounts["1110"]),
                "source_format": "csv",
                "mapping": json.dumps({"date": "Date", "amount": "Amount"}),
            },
            files={"file": ("march.csv", b"Date,Amount\n2026-03-01,1.00\n", "text/csv")},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 403

    def test_another_companys_payment_is_not_found(
        self, client: TestClient, session: Session, administrator: Person, books: TreasuryBooks
    ) -> None:
        """R10.AC7 — every endpoint is scoped to the company in its path."""
        sign_in(client, administrator)
        other = make_treasury_company(session)
        partner = make_partner(session, other.company_id, name="Elsewhere")
        payment = client.post(
            f"/api/v1/companies/{other.company_id}/payments",
            json=payment_body(other, str(partner.id)),
            headers=SAME_ORIGIN,
        )
        assert payment.status_code == 403

    def test_signing_out_closes_the_door(
        self, client: TestClient, base: str, books: TreasuryBooks
    ) -> None:
        client.post("/api/v1/auth/logout", headers=SAME_ORIGIN)
        assert client.get(f"{base}/payments").status_code == 401
