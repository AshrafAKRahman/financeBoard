"""Imports every module's models so Base.metadata is complete (Alembic, schema drift test)."""

import app.ledger.models
import app.platform.access.models
import app.platform.audit.models
import app.platform.identity.models
import app.platform.sequence.models
import app.platform.tenancy.models  # noqa: F401
