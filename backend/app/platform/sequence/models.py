"""Counter rows for gapless numbering.

The counter is read and bumped by one raw-SQL upsert (see ``api.next_number``); this
mapping exists so the table is part of ``Base.metadata`` and covered by the drift test.
"""

from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class SequenceCounter(Base):
    __tablename__ = "sequence_counter"

    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(primary_key=True)
    next_number: Mapped[int] = mapped_column(BigInteger)
