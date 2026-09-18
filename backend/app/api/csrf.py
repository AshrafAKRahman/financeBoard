"""Cookie-authenticated writes must come from our own origin (R12).

`SameSite=Lax` stops well-behaved browsers; this middleware stops everything else, and
covers login CSRF because it also guards the endpoints that have no cookie yet.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.errors import problem
from app.config import get_settings

logger = logging.getLogger("app.csrf")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Checked even without a session, so a cross-site page cannot sign someone in or burn an
# invitation link (R12.AC7).
ALWAYS_CHECKED_PATHS = frozenset({"/api/v1/auth/login"})


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in SAFE_METHODS:  # R12.AC6
            return await call_next(request)

        settings = get_settings()
        carries_session = settings.session_cookie_name in request.cookies
        accept_path = request.url.path in ALWAYS_CHECKED_PATHS or request.url.path.endswith(
            "/accept"
        )
        if not carries_session and not accept_path:
            return await call_next(request)

        origin = (request.headers.get("origin") or "").rstrip("/")
        fetch_site = request.headers.get("sec-fetch-site")

        if fetch_site == "same-origin" or (origin and origin in settings.accepted_origins):
            return await call_next(request)

        rejected = origin or fetch_site or "no origin header"
        logger.warning("Blocked cross-site request to %s from %s", request.url.path, rejected)
        _audit_rejection(request, rejected)
        return problem(
            "identity.csrf_check_failed",
            "this request did not come from an accepted origin",
        )


def _audit_rejection(request: Request, rejected: str) -> None:
    """R12.AC9 — record the attempt with the origin that was refused."""
    from app.db import transaction
    from app.platform.audit.api import record

    factory = getattr(request.app.state, "session_factory", None)
    try:
        with factory() if factory is not None else transaction() as session:
            record(
                session,
                action="request.csrf_blocked",
                detail={"origin": rejected, "path": request.url.path, "method": request.method},
            )
            session.commit()
    except Exception:  # never let auditing turn a refusal into a 500
        logger.exception("Could not record a blocked cross-site request")
