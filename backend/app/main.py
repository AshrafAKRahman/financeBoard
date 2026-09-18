"""The application: routes, the origin check, and the start-up checks that fail closed."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.csrf import CsrfMiddleware
from app.api.errors import domain_error_handler
from app.api.protection import check_routes, public
from app.api.routes import admin, auth, invitations
from app.db import pooled_engine, transaction
from app.platform.access.api import ensure_catalogue_seeded
from app.shared.errors import DomainError

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # Permissions added in code since the last migration are synced here; a database that
    # is not reachable yet must not stop the app, so /health can report the problem.
    factory = getattr(application.state, "session_factory", None)
    try:
        with factory() if factory is not None else transaction() as session:
            added = ensure_catalogue_seeded(session)
            session.commit()
        if added:
            logger.info("Added %s new permission(s) to the catalogue", added)
    except Exception:
        logger.exception("Could not sync the permission catalogue at start-up")
    yield


app = FastAPI(title="Finance ERP", version="0.2.0", lifespan=lifespan)
app.add_middleware(CsrfMiddleware)
app.add_exception_handler(DomainError, domain_error_handler)

app.include_router(auth.router)
app.include_router(invitations.router)
app.include_router(admin.router)


@app.get("/api/v1/health", tags=["health"])
@public
def health() -> JSONResponse:
    try:
        with pooled_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "degraded", "database": "unreachable"}, status_code=503)
    return JSONResponse({"status": "ok", "database": "ok"})


# Import time, not start-up time: an unprotected route must never reach a running server.
check_routes(app)
