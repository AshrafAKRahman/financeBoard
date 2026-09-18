"""Journal, defaults, template and rate endpoints (R10, R11, R12, R13)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.access.api import grant_role, set_role_permissions
from app.platform.tenancy.api import Company
from tests.api.conftest import SAME_ORIGIN, Person, sign_in

pytestmark = pytest.mark.db


@pytest.fixture
def base(client: TestClient, administrator: Person, company: Company) -> str:
    sign_in(client, administrator)
    return f"/api/v1/companies/{company.id}"


@pytest.fixture
def loaded(client: TestClient, base: str) -> dict:
    """A company with the Saudi chart in place, keyed by account code."""
    assert client.post(f"{base}/chart-templates/sa/load", headers=SAME_ORIGIN).status_code == 201
    return {row["code"]: row for row in client.get(f"{base}/accounts").json()}


def limited_caller(
    session: Session, client: TestClient, person: Person, company: Company, role, codes: list[str]
) -> None:
    set_role_permissions(session, role.id, codes)
    grant_role(session, user_id=person.user_id, company_id=company.id, role_id=role.id)
    session.commit()
    sign_in(client, person)


class TestJournals:
    def test_journals_are_listed_with_their_details(
        self, client: TestClient, base: str, loaded: dict
    ) -> None:
        """R10.AC1"""
        response = client.get(f"{base}/journals")
        assert response.status_code == 200
        journals = {journal["code"]: journal for journal in response.json()}
        assert journals["BNK"]["type"] == "bank"
        assert journals["BNK"]["default_account_id"] == loaded["1120"]["id"]

    def test_a_journal_is_created(self, client: TestClient, base: str, loaded: dict) -> None:
        """R10.AC2"""
        response = client.post(
            f"{base}/journals",
            json={"code": "BNK2", "name": "Second Bank", "type": "bank",
                  "default_account_id": loaded["1120"]["id"]},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 201
        assert response.json()["code"] == "BNK2"

    def test_a_journal_is_archived(self, client: TestClient, base: str, loaded: dict) -> None:
        """R10.AC3"""
        created = client.post(
            f"{base}/journals",
            json={"code": "TMP", "name": "Temporary", "type": "general"},
            headers=SAME_ORIGIN,
        ).json()

        archived = client.post(
            f"{base}/journals/{created['id']}/archive", headers=SAME_ORIGIN
        )
        assert archived.status_code == 200
        assert archived.json()["active"] is False
        assert "TMP" not in {j["code"] for j in client.get(f"{base}/journals").json()}

    def test_managing_needs_the_permission(
        self, client: TestClient, session: Session, bystander: Person, company: Company, reader_role
    ) -> None:
        """R10.AC4"""
        limited_caller(session, client, bystander, company, reader_role, ["journal:read"])
        chart = f"/api/v1/companies/{company.id}"

        assert client.get(f"{chart}/journals").status_code == 200
        refused = client.post(
            f"{chart}/journals",
            json={"code": "NOPE", "name": "No", "type": "general"},
            headers=SAME_ORIGIN,
        )
        assert refused.status_code == 403

    def test_journal_changes_are_audited(
        self, client: TestClient, session: Session, base: str, company: Company
    ) -> None:
        """R10.AC5"""
        client.post(
            f"{base}/journals",
            json={"code": "AUD", "name": "Audited", "type": "general"},
            headers=SAME_ORIGIN,
        )
        session.commit()

        detail = session.execute(
            text(
                "SELECT detail::text FROM audit_log WHERE action = 'journal.created' "
                "AND company_id = :c ORDER BY at DESC LIMIT 1"
            ),
            {"c": company.id},
        ).scalar_one()
        assert "AUD" in detail


class TestDefaults:
    def test_defaults_report_what_is_missing(self, client: TestClient, base: str) -> None:
        """R11.AC1"""
        response = client.get(f"{base}/defaults")
        assert response.status_code == 200
        body = response.json()
        assert "receivable" in body["missing"]
        assert body["accounts"]["receivable"] is None

    def test_a_default_is_set(self, client: TestClient, base: str, loaded: dict) -> None:
        """R11.AC2 — the template fills them, and they can be pointed elsewhere."""
        # 1130 Outstanding Receipts is a current asset, which suits the suspense default;
        # 1400 Prepaid Expenses is a prepayment and would (rightly) be refused.
        response = client.put(
            f"{base}/defaults/suspense",
            json={"account_id": loaded["1130"]["id"]},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 200
        assert response.json()["accounts"]["suspense"] == loaded["1130"]["id"]
        assert response.json()["missing"] == []

    def test_an_unsuitable_account_is_refused(
        self, client: TestClient, base: str, loaded: dict
    ) -> None:
        response = client.put(
            f"{base}/defaults/receivable",
            json={"account_id": loaded["2100"]["id"]},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "coa.default_subtype_mismatch"

    def test_setting_needs_the_manage_permission(
        self, client: TestClient, session: Session, bystander: Person, company: Company, reader_role
    ) -> None:
        """R11.AC3"""
        limited_caller(session, client, bystander, company, reader_role, ["account:read"])
        chart = f"/api/v1/companies/{company.id}"

        assert client.get(f"{chart}/defaults").status_code == 200
        refused = client.put(
            f"{chart}/defaults/suspense", json={"account_id": None}, headers=SAME_ORIGIN
        )
        assert refused.status_code == 403

    def test_setting_is_audited(
        self, client: TestClient, session: Session, base: str, company: Company, loaded: dict
    ) -> None:
        """R11.AC4"""
        client.put(
            f"{base}/defaults/suspense",
            json={"account_id": loaded["1500"]["id"]},
            headers=SAME_ORIGIN,
        )
        session.commit()

        detail = session.execute(
            text(
                "SELECT detail::text FROM audit_log WHERE action = 'company_default.set' "
                "AND company_id = :c ORDER BY at DESC LIMIT 1"
            ),
            {"c": company.id},
        ).scalar_one()
        assert "suspense" in detail and "1500" in detail


class TestTemplates:
    def test_templates_can_be_listed(self, client: TestClient, base: str) -> None:
        """R12.AC3"""
        response = client.get(f"{base}/chart-templates")
        assert response.status_code == 200
        templates = {template["key"]: template for template in response.json()}
        assert "sa" in templates
        assert "Saudi" in templates["sa"]["name"]
        assert templates["sa"]["description"]

    def test_loading_builds_the_whole_chart(self, client: TestClient, base: str) -> None:
        """R12.AC1"""
        response = client.post(f"{base}/chart-templates/sa/load", headers=SAME_ORIGIN)
        assert response.status_code == 201
        summary = response.json()
        assert summary["accounts"] > 40
        assert summary["journals"] == 5
        assert summary["defaults"] == 8

        assert client.get(f"{base}/defaults").json()["missing"] == []
        readiness = client.get(f"{base}/chart-readiness").json()
        assert {finding["code"] for finding in readiness} <= {"coa.currency_without_rate"}

    def test_loading_twice_is_refused(self, client: TestClient, base: str, loaded: dict) -> None:
        response = client.post(f"{base}/chart-templates/sa/load", headers=SAME_ORIGIN)
        assert response.status_code == 409
        assert response.json()["code"] == "coa.chart_not_empty"

    def test_loading_needs_the_permission(
        self, client: TestClient, session: Session, bystander: Person, company: Company, reader_role
    ) -> None:
        """R12.AC2"""
        limited_caller(session, client, bystander, company, reader_role, ["account:read"])
        refused = client.post(
            f"/api/v1/companies/{company.id}/chart-templates/sa/load", headers=SAME_ORIGIN
        )
        assert refused.status_code == 403

    def test_loading_is_audited(
        self, client: TestClient, session: Session, base: str, company: Company, loaded: dict
    ) -> None:
        """R12.AC4"""
        session.commit()
        detail = session.execute(
            text(
                "SELECT detail::text FROM audit_log WHERE action = 'chart_template.loaded' "
                "AND company_id = :c"
            ),
            {"c": company.id},
        ).scalar_one()
        assert '"sa"' in detail


class TestRates:
    def test_a_rate_is_recorded_and_listed(self, client: TestClient, base: str) -> None:
        """R13.AC1 and R13.AC2"""
        response = client.put(
            f"{base}/exchange-rates",
            json={"currency_code": "USD", "rate_date": "2026-03-01", "rate": "3.7500"},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 200
        assert response.json()["currency_code"] == "USD"

        listed = client.get(f"{base}/exchange-rates", params={"currency_code": "USD"}).json()
        assert [row["rate_date"] for row in listed] == ["2026-03-01"]

    def test_rates_come_back_in_date_order(self, client: TestClient, base: str) -> None:
        for day in (5, 1, 3):
            client.put(
                f"{base}/exchange-rates",
                json={"currency_code": "EUR", "rate_date": f"2026-03-0{day}", "rate": "4.0"},
                headers=SAME_ORIGIN,
            )
        listed = client.get(f"{base}/exchange-rates", params={"currency_code": "EUR"}).json()
        assert [row["rate_date"] for row in listed] == [
            "2026-03-01",
            "2026-03-03",
            "2026-03-05",
        ]

    def test_an_import_reports_each_rejected_row(self, client: TestClient, base: str) -> None:
        """R13.AC3"""
        response = client.post(
            f"{base}/exchange-rates/import",
            json=[
                {"currency_code": "USD", "rate_date": "2026-04-01", "rate": "3.75"},
                {"currency_code": "SAR", "rate_date": "2026-04-01", "rate": "1"},
                {"currency_code": "USD", "rate_date": "2026-04-02", "rate": "-2"},
            ],
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["recorded"] == 1
        assert [row["row"] for row in body["rejected"]] == [2, 3]
        assert all(row["reason"] for row in body["rejected"])

    def test_entering_rates_needs_the_permission(
        self, client: TestClient, session: Session, bystander: Person, company: Company, reader_role
    ) -> None:
        """R13.AC4"""
        limited_caller(session, client, bystander, company, reader_role, ["rate:read"])
        chart = f"/api/v1/companies/{company.id}"

        assert client.get(f"{chart}/exchange-rates").status_code == 200
        refused = client.put(
            f"{chart}/exchange-rates",
            json={"currency_code": "USD", "rate_date": "2026-03-01", "rate": "3.75"},
            headers=SAME_ORIGIN,
        )
        assert refused.status_code == 403
