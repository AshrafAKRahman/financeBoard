from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Numeric, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

MONEY = Numeric(20, 6, asdecimal=True)


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012
        str: Text(),  # the migrations use TEXT everywhere, not VARCHAR(n)
        UUID: Uuid(as_uuid=True),
        Decimal: MONEY,
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }
