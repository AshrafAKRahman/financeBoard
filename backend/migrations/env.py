from alembic import context

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.db import make_engine
from app.shared.db import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    # Tests pass an open connection; otherwise use the direct (non-pooled) Neon endpoint.
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    from app.config import get_settings

    engine = make_engine(get_settings().database_url_direct, pooled=False, pool_size=1)
    with engine.connect() as connection:
        _run(connection)
    engine.dispose()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported; run against a Neon branch.")

run_migrations_online()
