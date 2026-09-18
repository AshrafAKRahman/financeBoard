"""The financial reports over HTTP (R8, R9)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.platform.access.api import grant_role, set_role_permissions
from app.platform.access.models import ADMINISTRATOR_ROLE_ID, Role
from app.shared.ids import uuid7
from tests.api.conftest import SAME_ORIGIN, Person, sign_in
from tests.factories import TreasuryBooks, make_partner, make_treasury_company

pytestmark = pytest.mark.db

JANUARY = "2026-01-15"
YEAR_START = "2026-01-01"
YEAR_END = "2026-12-31"


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
    return f"/api/v1/companies/{books.company_id}/reports"


@pytest.fixture
def customer(session: Session, books: TreasuryBooks) -> str:
    return str(make_partner(session, books.company_id, name="Al Noor Est", type="customer").id)


@pytest.fixture
def traded(client: TestClient, books: TreasuryBooks, customer: str) -> None:
    """One invoice through the API, so the reports have something to say."""
    company = f"/api/v1/companies/{books.company_id}"
    created = client.post(
        f"{company}/documents",
        json={
            "type": "out_invoice",
            "partner_id": customer,
            "journal_id": str(books.journals["INV"]),
            "date": JANUARY,
            "currency_code": "SAR",
            "lines": [
                {
                    "description": "Consultancy",
                    "quantity": "1",
                    "unit_price": "10000.00",
                    "account_id": str(books.accounts["4100"]),
                    "tax_ids": [str(books.taxes["sale"])],
                }
            ],
        },
        headers=SAME_ORIGIN,
    )
    assert created.status_code == 201, created.text
    posted = client.post(f"{company}/documents/{created.json()['id']}/post", headers=SAME_ORIGIN)
    assert posted.status_code == 200, posted.text


def period(**extra) -> dict:
    return {"start": YEAR_START, "end": YEAR_END, **extra}


class TestTheReports:
    def test_the_trial_balance_balances(self, client: TestClient, base: str, traded: None) -> None:
        """R1, R9.AC3"""
        response = client.get(f"{base}/trial-balance", params=period())

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["balances"] is True
        assert Decimal(body["total_debit"]) == Decimal("11500.000000")

    def test_the_profit_and_loss(self, client: TestClient, base: str, traded: None) -> None:
        """R2"""
        body = client.get(f"{base}/profit-and-loss", params=period()).json()

        assert Decimal(body["total_income"]) == Decimal("10000.000000")
        assert Decimal(body["net_result"]) == Decimal("10000.000000")

    def test_a_comparison_period_can_be_asked_for(
        self, client: TestClient, base: str, traded: None
    ) -> None:
        """R2.AC8"""
        body = client.get(f"{base}/profit-and-loss", params=period(comparison=True)).json()
        assert body["comparison"] is not None

    def test_the_balance_sheet_balances(self, client: TestClient, base: str, traded: None) -> None:
        """R3"""
        body = client.get(f"{base}/balance-sheet", params={"on": YEAR_END}).json()

        assert body["balances"] is True
        assert Decimal(body["current_year_earnings"]) == Decimal("10000.000000")

    def test_the_cash_flow_reconciles(self, client: TestClient, base: str, traded: None) -> None:
        """R4"""
        body = client.get(f"{base}/cash-flow", params=period()).json()
        assert body["reconciles"] is True

    def test_aged_receivables(self, client: TestClient, base: str, traded: None) -> None:
        """R5"""
        body = client.get(f"{base}/aged-receivables", params={"on": YEAR_END}).json()

        assert Decimal(body["total"]) == Decimal("11500.000000")
        assert body["partners"][0]["partner_name"] == "Al Noor Est"

    def test_aged_payables_are_a_separate_report(
        self, client: TestClient, base: str, traded: None
    ) -> None:
        """R5.AC6"""
        body = client.get(f"{base}/aged-payables", params={"on": YEAR_END}).json()
        assert Decimal(body["total"]) == Decimal(0)

    def test_the_vat_return(self, client: TestClient, base: str, traded: None) -> None:
        """R6"""
        body = client.get(f"{base}/vat-return", params=period()).json()

        assert Decimal(body["output_tax"]) == Decimal("1500.000000")
        assert Decimal(body["net_tax_due"]) == Decimal("1500.000000")
        assert body["sales"][0]["number"] == 1

    def test_an_accounts_detail(
        self, client: TestClient, base: str, books: TreasuryBooks, traded: None
    ) -> None:
        """R7"""
        account = books.accounts["1200"]
        body = client.get(f"{base}/accounts/{account}/detail", params=period()).json()

        assert len(body["lines"]) == 1
        assert Decimal(body["closing_balance"]) == Decimal("11500.000000")
        assert body["lines"][0]["document_number"].startswith("INV/")


class TestTheEnvelope:
    def test_every_report_says_what_it_covers(
        self, client: TestClient, base: str, traded: None
    ) -> None:
        """R8.AC5"""
        body = client.get(f"{base}/trial-balance", params=period()).json()

        assert body["meta"]["company_name"] == "Jeddah Trading"
        assert body["meta"]["currency_code"] == "SAR"
        assert body["meta"]["period_start"] == YEAR_START
        assert body["meta"]["generated_at"]

    def test_rows_carry_their_account_so_a_screen_can_link(
        self, client: TestClient, base: str, traded: None
    ) -> None:
        """R9.AC4"""
        body = client.get(f"{base}/trial-balance", params=period(hide_unused=True)).json()

        def walk(rows):
            for row in rows:
                yield row
                yield from walk(row["children"])

        leaves = [row for row in walk(body["rows"]) if not row["is_group"]]
        assert leaves
        assert all(row["account_id"] for row in leaves)

    def test_without_a_period_it_uses_the_year_to_date(
        self, client: TestClient, base: str, traded: None
    ) -> None:
        """R8.AC2"""
        response = client.get(f"{base}/trial-balance")

        assert response.status_code == 200
        assert response.json()["meta"]["period_label"] == "Fiscal year to date"

    def test_a_named_period_is_accepted(self, client: TestClient, base: str, traded: None) -> None:
        """R8.AC3"""
        response = client.get(f"{base}/vat-return", params={"period": "q1"})

        assert response.status_code == 200
        assert response.json()["meta"]["period_label"].startswith("Q1")


class TestWhatIsRefused:
    def test_a_backwards_period_is_a_422(self, client: TestClient, base: str) -> None:
        """R9.AC5, NFR5"""
        response = client.get(
            f"{base}/trial-balance", params={"start": YEAR_END, "end": YEAR_START}
        )

        assert response.status_code == 422
        assert response.json()["code"] == "reporting.invalid_period"

    def test_a_period_nobody_defined_is_a_422(self, client: TestClient, base: str) -> None:
        response = client.get(f"{base}/trial-balance", params={"period": "last-fortnight"})

        assert response.status_code == 422
        assert response.json()["code"] == "reporting.invalid_period"

    def test_an_unknown_account_is_a_404(self, client: TestClient, base: str) -> None:
        response = client.get(f"{base}/accounts/{uuid7()}/detail", params=period())

        assert response.status_code == 404
        assert response.json()["code"] == "reporting.account_not_found"

    def test_signing_out_closes_the_door(self, client: TestClient, base: str) -> None:
        client.post("/api/v1/auth/logout", headers=SAME_ORIGIN)
        assert client.get(f"{base}/trial-balance").status_code == 401


class TestPermissions:
    @pytest.fixture
    def outsider(self, session: Session, books: TreasuryBooks, mailer, client: TestClient):
        """Someone in the company who may read invoices but not the profit."""
        from tests.api.conftest import make_person

        person = make_person(session, mailer, name="Clerk")
        role = Role(id=uuid7(), name=f"Clerk {uuid7().hex[-6:]}")
        session.add(role)
        session.flush()
        set_role_permissions(session, role.id, ["invoice:read", "account:read"])
        grant_role(session, user_id=person.user_id, company_id=books.company_id, role_id=role.id)
        session.commit()
        sign_in(client, person)
        return person

    @pytest.mark.parametrize(
        "path",
        [
            "trial-balance",
            "profit-and-loss",
            "balance-sheet",
            "cash-flow",
            "aged-receivables",
            "aged-payables",
            "vat-return",
        ],
    )
    def test_reading_the_chart_is_not_reading_the_profit(
        self, client: TestClient, books: TreasuryBooks, outsider, path: str
    ) -> None:
        """R9.AC2 — a report shows the whole position, so it has its own permission."""
        response = client.get(f"/api/v1/companies/{books.company_id}/reports/{path}")
        assert response.status_code == 403

    def test_another_companys_reports_are_refused(
        self, client: TestClient, session: Session, administrator: Person, books: TreasuryBooks
    ) -> None:
        """R8.AC1, R8.AC4 — scoped to the company in the path."""
        sign_in(client, administrator)
        other = make_treasury_company(session)

        response = client.get(f"/api/v1/companies/{other.company_id}/reports/trial-balance")
        assert response.status_code == 403
