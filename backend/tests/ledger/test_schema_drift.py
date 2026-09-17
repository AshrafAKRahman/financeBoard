"""The ORM mappings must describe the same schema the migrations create.

Alembic's autogenerate comparison does not look at CHECK constraints or triggers, so
this catches column, type, index and foreign-key drift only. Behaviour is covered by
tests/invariants/.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.shared.db import Base


def test_orm_models_match_the_migrated_schema(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], "\n".join(repr(d) for d in differences)
