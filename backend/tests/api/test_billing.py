"""Invoicing over HTTP (R10, R11.AC3)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.billing.models import Tax
from app.coa.accounts import list_chart
from app.coa.journals import list_journals
from app.platform.access.api import grant_role, set_role_permissions
from app.platform.tenancy.api import Company
from app.shared.ids import uuid7
from tests.api.conftest import SAME_ORIGIN, Person, sign_in

pytestmark = pytest.mark.db

TODAY = "2026-03-01"


@pytest.fixture
def billing_company(session: Session, administrator: Person):
    """A company with a small chart, granted to the signed-in administrator."""
    from app.platform.access.models import ADMINISTRATOR_ROLE_ID
    from tests.factories import make_small_billing_company

    company = make_small_billing_company(session)
    grant_role(
        session,
        user_id=administrator.user_id,
        company_id=company.id,
        role_id=ADMINISTRATOR_ROLE_ID,
    )
    session.commit()
    return company


@pytest.fixture
def base(client: TestClient, administrator: Person, billing_company: Company) -> str:
    sign_in(client, administrator)
    return f"/api/v1/companies/{billing_company.id}"


@pytest.fixture
def context(session: Session, billing_company: Company) -> dict:
    accounts = {row.account.code: row.account.id for row in list_chart(session, billing_company.id)}
    journals = {j.code: j.id for j in list_journals(session, billing_company.id)}
    vat = session.execute(
        select(Tax).where(Tax.company_id == billing_company.id, Tax.type == "sale")
    ).scalar_one()
    return {"accounts": accounts, "journals": journals, "vat": vat}


def invoice_body(context: dict, partner_id, **overrides) -> dict:
    body = {
        "type": "out_invoice",
        "partner_id": str(partner_id),
        "journal_id": str(context["journals"]["INV"]),
        "date": TODAY,
        "lines": [
            {
                "description": "Consulting",
                "description_ar": "استشارات",
                "quantity": "2",
                "unit_price": "500.00",
                "account_id": str(context["accounts"]["4100"]),
                "tax_ids": [str(context["vat"].id)],
            }
        ],
    }
    body.update(overrides)
    return body


@pytest.fixture
def customer_id(client: TestClient, base: str) -> str:
    response = client.post(
        f"{base}/partners",
        json={"name": "Al Noor Est", "type": "customer", "vat_number": "310000000000003"},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestPartnersAndTaxes:
    def test_a_partner_is_created_and_listed(
        self, client: TestClient, base: str, customer_id: str
    ) -> None:
        """R10.AC8"""
        listed = client.get(f"{base}/partners").json()
        assert customer_id in {partner["id"] for partner in listed}
        assert listed[0]["vat_number"] == "310000000000003"

    def test_a_bad_vat_number_is_refused_with_its_code(self, client: TestClient, base: str) -> None:
        response = client.post(
            f"{base}/partners",
            json={"name": "Wrong", "type": "customer", "vat_number": "12345"},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invoicing.invalid_vat_number"

    def test_a_tax_is_created(self, client: TestClient, base: str, context: dict) -> None:
        """R10.AC7"""
        response = client.post(
            f"{base}/taxes",
            json={
                "name": "VAT 5% (special)",
                "rate": "5",
                "type": "sale",
                "account_id": str(context["accounts"]["2200"]),
            },
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 201
        assert Decimal(response.json()["rate"]) == Decimal("5")

    def test_taxes_can_be_filtered_by_date(self, client: TestClient, base: str) -> None:
        listed = client.get(f"{base}/taxes", params={"on": TODAY}).json()
        assert {tax["name"] for tax in listed} >= {"VAT 15%"}


class TestDocuments:
    def test_a_draft_is_created_with_its_totals(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        """R10.AC4"""
        response = client.post(
            f"{base}/documents", json=invoice_body(context, customer_id), headers=SAME_ORIGIN
        )

        assert response.status_code == 201
        body = response.json()
        assert body["state"] == "draft"
        assert body["number"] is None
        assert body["net"] == "1000.00"
        assert body["tax_total"] == "150.00"
        assert body["total"] == "1150.00"
        assert body["lines"][0]["description_ar"] == "استشارات"
        assert body["tax_groups"][0]["vat_category"] == "standard"

    def test_a_document_is_read_back_in_full(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        """R10.AC3"""
        created = client.post(
            f"{base}/documents", json=invoice_body(context, customer_id), headers=SAME_ORIGIN
        ).json()

        response = client.get(f"{base}/documents/{created['id']}")
        assert response.status_code == 200
        assert response.json()["lines"][0]["net"] == "1000.00"
        assert response.json()["payment_state"] == "not_paid"

    def test_documents_are_listed_newest_first_and_filtered(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        """R10.AC1 and R10.AC2"""
        client.post(
            f"{base}/documents", json=invoice_body(context, customer_id), headers=SAME_ORIGIN
        )
        client.post(
            f"{base}/documents",
            json=invoice_body(context, customer_id, date="2026-05-01"),
            headers=SAME_ORIGIN,
        )

        listed = client.get(f"{base}/documents").json()
        assert [document["date"] for document in listed] == ["2026-05-01", "2026-03-01"]

        filtered = client.get(f"{base}/documents", params={"state": "draft"}).json()
        assert len(filtered) == 2
        assert client.get(f"{base}/documents", params={"since": "2026-04-01"}).json() != []

    def test_a_draft_is_changed_and_deleted(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        created = client.post(
            f"{base}/documents", json=invoice_body(context, customer_id), headers=SAME_ORIGIN
        ).json()

        patched = client.patch(
            f"{base}/documents/{created['id']}",
            json={"narration": "March consulting"},
            headers=SAME_ORIGIN,
        )
        assert patched.status_code == 200
        assert patched.json()["narration"] == "March consulting"

        assert (
            client.delete(f"{base}/documents/{created['id']}", headers=SAME_ORIGIN).status_code
            == 204
        )
        assert client.get(f"{base}/documents/{created['id']}").status_code == 404

    def test_posting_numbers_it_and_returns_the_entry(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        """R10.AC5 and R11.AC4"""
        created = client.post(
            f"{base}/documents", json=invoice_body(context, customer_id), headers=SAME_ORIGIN
        ).json()

        posted = client.post(f"{base}/documents/{created['id']}/post", headers=SAME_ORIGIN)
        assert posted.status_code == 200
        body = posted.json()
        assert body["state"] == "posted"
        assert body["number"].startswith("INV/2026/")
        assert body["journal_entry_id"]

    def test_a_posted_document_cannot_be_edited(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        created = client.post(
            f"{base}/documents", json=invoice_body(context, customer_id), headers=SAME_ORIGIN
        ).json()
        client.post(f"{base}/documents/{created['id']}/post", headers=SAME_ORIGIN)

        refused = client.patch(
            f"{base}/documents/{created['id']}", json={"narration": "no"}, headers=SAME_ORIGIN
        )
        assert refused.status_code == 409
        assert refused.json()["code"] == "invoicing.posted_immutable"

    def test_cancelling_and_crediting(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        first = client.post(
            f"{base}/documents", json=invoice_body(context, customer_id), headers=SAME_ORIGIN
        ).json()
        client.post(f"{base}/documents/{first['id']}/post", headers=SAME_ORIGIN)

        note = client.post(f"{base}/documents/{first['id']}/credit-note", headers=SAME_ORIGIN)
        assert note.status_code == 201
        assert note.json()["type"] == "out_credit"
        assert note.json()["origin_document_id"] == first["id"]

        second = client.post(
            f"{base}/documents", json=invoice_body(context, customer_id), headers=SAME_ORIGIN
        ).json()
        client.post(f"{base}/documents/{second['id']}/post", headers=SAME_ORIGIN)
        cancelled = client.post(
            f"{base}/documents/{second['id']}/cancel",
            json={"reason": "duplicate"},
            headers=SAME_ORIGIN,
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"

    def test_another_companys_document_is_not_found(
        self, client: TestClient, session: Session, base: str, administrator: Person
    ) -> None:
        from app.platform.access.models import ADMINISTRATOR_ROLE_ID
        from tests.factories import make_small_billing_company

        other = make_small_billing_company(session)
        grant_role(
            session,
            user_id=administrator.user_id,
            company_id=other.id,
            role_id=ADMINISTRATOR_ROLE_ID,
        )
        session.commit()

        response = client.get(f"{base}/documents/{uuid7()}")
        assert response.status_code == 404
        assert response.json()["code"] == "invoicing.document_not_found"


class TestPermissions:
    def grant(self, session: Session, person: Person, company: Company, role, codes: list[str]):
        set_role_permissions(session, role.id, codes)
        grant_role(session, user_id=person.user_id, company_id=company.id, role_id=role.id)
        session.commit()

    def test_reading_does_not_allow_writing(
        self,
        client: TestClient,
        session: Session,
        bystander: Person,
        billing_company: Company,
        reader_role,
        context: dict,
    ) -> None:
        """R10.AC6"""
        self.grant(session, bystander, billing_company, reader_role, ["invoice:read"])
        sign_in(client, bystander)
        base = f"/api/v1/companies/{billing_company.id}"

        assert client.get(f"{base}/documents").status_code == 200
        refused = client.post(
            f"{base}/documents", json=invoice_body(context, uuid7()), headers=SAME_ORIGIN
        )
        assert refused.status_code == 403
        assert refused.json()["code"] == "identity.permission_denied"

    def test_managing_does_not_allow_issuing(
        self,
        client: TestClient,
        session: Session,
        bystander: Person,
        billing_company: Company,
        reader_role,
        context: dict,
    ) -> None:
        """R10.AC5 — issuing is its own permission."""
        self.grant(
            session,
            bystander,
            billing_company,
            reader_role,
            ["invoice:read", "invoice:manage", "partner:manage"],
        )
        sign_in(client, bystander)
        base = f"/api/v1/companies/{billing_company.id}"

        partner = client.post(
            f"{base}/partners", json={"name": "Buyer", "type": "customer"}, headers=SAME_ORIGIN
        ).json()
        created = client.post(
            f"{base}/documents", json=invoice_body(context, partner["id"]), headers=SAME_ORIGIN
        )
        assert created.status_code == 201

        refused = client.post(f"{base}/documents/{created.json()['id']}/post", headers=SAME_ORIGIN)
        assert refused.status_code == 403


class TestRecurring:
    def test_a_template_generates_a_draft(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        created = client.post(
            f"{base}/recurring-templates",
            json={
                "name": "Monthly retainer",
                "partner_id": customer_id,
                "journal_id": str(context["journals"]["INV"]),
                "next_date": TODAY,
                "lines": [
                    {
                        "description": "Retainer",
                        "quantity": "1",
                        "unit_price": "2000.00",
                        "account_id": str(context["accounts"]["4100"]),
                        "tax_ids": [str(context["vat"].id)],
                    }
                ],
            },
            headers=SAME_ORIGIN,
        )
        assert created.status_code == 201

        generated = client.post(
            f"{base}/recurring-templates/generate", json={"on": TODAY}, headers=SAME_ORIGIN
        )
        assert generated.status_code == 200
        assert generated.json()["count"] == 1
        assert generated.json()["from_templates"] == ["Monthly retainer"]

        again = client.post(
            f"{base}/recurring-templates/generate", json={"on": TODAY}, headers=SAME_ORIGIN
        )
        assert again.json()["count"] == 0

    def test_a_template_can_be_paused(
        self, client: TestClient, base: str, context: dict, customer_id: str
    ) -> None:
        created = client.post(
            f"{base}/recurring-templates",
            json={
                "name": "Paused",
                "partner_id": customer_id,
                "journal_id": str(context["journals"]["INV"]),
                "next_date": TODAY,
                "lines": [
                    {
                        "description": "Retainer",
                        "quantity": "1",
                        "unit_price": "100.00",
                        "account_id": str(context["accounts"]["4100"]),
                    }
                ],
            },
            headers=SAME_ORIGIN,
        ).json()

        paused = client.post(
            f"{base}/recurring-templates/{created['id']}/pause", headers=SAME_ORIGIN
        )
        assert paused.status_code == 200
        assert paused.json()["active"] is False

        assert (
            client.post(
                f"{base}/recurring-templates/generate", json={"on": TODAY}, headers=SAME_ORIGIN
            ).json()["count"]
            == 0
        )


def test_changes_are_audited(
    client: TestClient,
    session: Session,
    base: str,
    billing_company: Company,
    context: dict,
    customer_id: str,
) -> None:
    """R11.AC3"""
    client.post(
        f"{base}/taxes",
        json={
            "name": "Audited tax",
            "rate": "5",
            "type": "sale",
            "account_id": str(context["accounts"]["2200"]),
        },
        headers=SAME_ORIGIN,
    )
    session.commit()

    actions = set(
        session.execute(
            text("SELECT action FROM audit_log WHERE company_id = :c"),
            {"c": billing_company.id},
        ).scalars()
    )
    assert {"partner.created", "tax.created"} <= actions
