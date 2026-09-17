"""Imports every module's models so Base.metadata is complete (Alembic, schema drift test)."""

import app.ledger.models
import app.platform.sequence.models
import app.platform.tenancy.models  # noqa: F401
