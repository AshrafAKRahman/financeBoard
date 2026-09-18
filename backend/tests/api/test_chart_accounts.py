"""Account endpoints (R9)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.tenancy.api import Company
from app.shared.ids import uuid7
from tests.api.conftest import SAME_ORIGIN, Person, sign_in

pytestmark = pytest.mark.db


@pytest.fixture
def signed_in(client: TestClient, administrator: Person, company: Company) -> str:
    sign_in(client, administrator)
    return f"/api/v1/companies/{company.id}"


def make(client: TestClient, base: str, code: str, **body):
    payload = {
        "code": code,
        "name": body.pop("name", f"Account {code}"),
        "type": body.pop("type", "asset"),
        "subtype": body.pop("subtype", "current_asset"),
        **body,
    }
    return client.post(f"{base}/accounts", json=payload, headers=SAME_ORIGIN)


def test_an_account_is_created_and_returned(client: TestClient, signed_in: str) -> None:
    """R9.AC3"""
    response = make(client, signed_in, "1170", name="Petty Cash", subtype="bank_cash",
                    name_ar="النقدية")

    assert response.status_code == 201
    body = response.json()
    assert body["id"] and body["code"] == "1170"
    assert body["name_ar"] == "النقدية"
    assert body["active"] is True


def test_the_chart_comes_back_with_its_hierarchy(client: TestClient, signed_in: str) -> None:
    """R9.AC1"""
    group = make(client, signed_in, "1800", name="Group", is_group=True).json()
    make(client, signed_in, "1810", name="Child", parent_id=group["id"])

    response = client.get(f"{signed_in}/accounts")
    assert response.status_code == 200
    rows = {row["code"]: row for row in response.json()}
    assert rows["1800"]["depth"] == 1
    assert rows["1810"]["depth"] == 2
    assert rows["1810"]["parent_id"] == group["id"]


def test_the_chart_can_be_searched(client: TestClient, signed_in: str) -> None:
    """R9.AC2"""
    make(client, signed_in, "1820", name="Marketing Prepayment", subtype="prepayment")
    make(client, signed_in, "1830", name="Rent Deposit")

    found = client.get(f"{signed_in}/accounts", params={"search": "marketing"}).json()
    assert [row["code"] for row in found] == ["1820"]


def test_an_account_is_updated(client: TestClient, signed_in: str) -> None:
    """R9.AC4"""
    created = make(client, signed_in, "1840").json()
    response = client.patch(
        f"{signed_in}/accounts/{created['id']}",
        json={"name": "Renamed", "cash_flow_tag": "investing"},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["cash_flow_tag"] == "investing"


def test_an_account_is_archived_and_disappears_from_the_chart(
    client: TestClient, signed_in: str
) -> None:
    """R9.AC5"""
    created = make(client, signed_in, "1850").json()
    response = client.post(
        f"{signed_in}/accounts/{created['id']}/archive", headers=SAME_ORIGIN
    )
    assert response.status_code == 200
    assert response.json()["active"] is False

    codes = {row["code"] for row in client.get(f"{signed_in}/accounts").json()}
    assert "1850" not in codes

    with_archived = client.get(
        f"{signed_in}/accounts", params={"include_archived": True}
    ).json()
    assert "1850" in {row["code"] for row in with_archived}


def test_an_unused_account_can_be_deleted(client: TestClient, signed_in: str) -> None:
    created = make(client, signed_in, "1860").json()
    assert client.delete(
        f"{signed_in}/accounts/{created['id']}", headers=SAME_ORIGIN
    ).status_code == 204
    assert "1860" not in {row["code"] for row in client.get(f"{signed_in}/accounts").json()}


def test_creating_needs_the_manage_permission(
    client: TestClient, session: Session, bystander: Person, company: Company, reader_role
) -> None:
    """R9.AC6 — reading is not managing."""
    from app.platform.access.api import grant_role, set_role_permissions

    set_role_permissions(session, reader_role.id, ["account:read"])
    grant_role(
        session, user_id=bystander.user_id, company_id=company.id, role_id=reader_role.id
    )
    session.commit()

    sign_in(client, bystander)
    base = f"/api/v1/companies/{company.id}"
    assert client.get(f"{base}/accounts").status_code == 200

    refused = make(client, base, "1870")
    assert refused.status_code == 403
    assert refused.json()["code"] == "identity.permission_denied"


def test_another_companys_account_is_not_found(
    client: TestClient, session: Session, administrator: Person, company: Company
) -> None:
    """R9.AC7"""
    from app.coa.accounts import AccountData, create_account
    from app.platform.access.api import grant_role
    from app.platform.access.models import ADMINISTRATOR_ROLE_ID

    other = Company(id=uuid7(), name="Second Co", base_currency="SAR")
    session.add(other)
    session.flush()
    grant_role(
        session,
        user_id=administrator.user_id,
        company_id=other.id,
        role_id=ADMINISTRATOR_ROLE_ID,
    )
    theirs = create_account(
        session,
        other.id,
        AccountData(code="1880", name="Theirs", type="asset", subtype="current_asset"),
    )
    session.commit()

    sign_in(client, administrator)
    response = client.patch(
        f"/api/v1/companies/{company.id}/accounts/{theirs.id}",
        json={"name": "Stolen"},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "coa.account_not_found"


def test_changes_are_audited(
    client: TestClient, session: Session, signed_in: str, company: Company
) -> None:
    """R9.AC8"""
    created = make(client, signed_in, "1890", name="Audited").json()
    client.patch(
        f"{signed_in}/accounts/{created['id']}", json={"name": "Audited Twice"},
        headers=SAME_ORIGIN,
    )
    session.commit()

    rows = (
        session.execute(
            text(
                "SELECT action, detail::text FROM audit_log WHERE target_id = :id ORDER BY at"
            ),
            {"id": created["id"]},
        )
        .all()
    )
    assert [row.action for row in rows] == ["account.created", "account.updated"]
    assert "1890" in rows[0].detail


def test_a_bad_account_is_refused_with_a_useful_code(
    client: TestClient, signed_in: str
) -> None:
    duplicate = make(client, signed_in, "1900")
    assert duplicate.status_code == 201
    again = make(client, signed_in, "1900")
    assert again.status_code == 409
    assert again.json()["code"] == "coa.duplicate_code"

    cycle_parent = make(client, signed_in, "1910", is_group=True).json()
    child = make(client, signed_in, "1920", is_group=True, parent_id=cycle_parent["id"]).json()
    looped = client.patch(
        f"{signed_in}/accounts/{cycle_parent['id']}",
        json={"parent_id": child["id"]},
        headers=SAME_ORIGIN,
    )
    assert looped.status_code == 422
    assert looped.json()["code"] == "coa.hierarchy_cycle"
