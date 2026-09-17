"""Gapless document numbering.

The upsert takes a row lock on the counter that is held until the surrounding
transaction ends, so concurrent callers for the same scope queue up, and a rollback
returns the number. Numbers are therefore unique and gapless per (company, scope, period).
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_NEXT = text(
    """
    INSERT INTO sequence_counter AS sc (company_id, scope, period, next_number)
    VALUES (:company_id, :scope, :period, 2)
    ON CONFLICT (company_id, scope, period)
    DO UPDATE SET next_number = sc.next_number + 1
    RETURNING sc.next_number - 1
    """
)


def next_number(session: Session, company_id: UUID, scope: str, period: str) -> int:
    return session.execute(
        _NEXT, {"company_id": company_id, "scope": scope, "period": period}
    ).scalar_one()
