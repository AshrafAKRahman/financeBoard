"""Every route says what it needs, and the app refuses to start if one does not (R7).

Marking is a decorator on the endpoint function, so the declaration sits with the code it
guards and cannot be forgotten in a router include.
"""

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.platform.access.permissions import CODES

PUBLIC = "public"
ATTRIBUTE = "__route_access__"

# Only these may be reachable without a session (R7.AC5).
ALLOWED_PUBLIC_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/invitations/{token}",
    "/api/v1/invitations/{token}/accept",
    # The web application's own HTML and assets. It contains no data: every figure it shows
    # is fetched afterwards from an endpoint that does check (decision D16).
    "/{path:path}",
}


class RouteProtectionError(RuntimeError):
    """Raised at start-up; the application does not serve traffic."""


def public(func: Callable[..., Any]) -> Callable[..., Any]:
    """Reachable without signing in."""
    setattr(func, ATTRIBUTE, PUBLIC)
    return func


def authenticated(func: Callable[..., Any]) -> Callable[..., Any]:
    """Any signed-in user; no particular permission (own profile, own password)."""
    setattr(func, ATTRIBUTE, "authenticated")
    return func


def needs(permission: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Requires this permission — in the company named in the path, or in any company for
    routes that are not company-scoped."""

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, ATTRIBUTE, permission)
        return func

    return decorate


def declared_access(route: APIRoute) -> str | None:
    return getattr(route.endpoint, ATTRIBUTE, None)


def iter_api_routes(app: FastAPI) -> Iterator[APIRoute]:
    """Every endpoint, including those inside included routers (which newer FastAPI
    versions keep nested rather than flattening into ``app.routes``)."""

    def walk(routes: Iterable[Any]) -> Iterator[APIRoute]:
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            # An included router is kept as a wrapper around the original router.
            nested = getattr(route, "routes", None) or getattr(
                getattr(route, "original_router", None), "routes", None
            )
            if nested:
                yield from walk(nested)

    yield from walk(app.routes)


def check_routes(app: FastAPI) -> None:
    """Fail closed: an undeclared route, an unknown permission, or a public route that is
    not on the short list stops start-up (R7.AC1, R7.AC2, R7.AC5)."""
    problems: list[str] = []

    for route in iter_api_routes(app):
        access = declared_access(route)
        where = f"{sorted(route.methods)} {route.path}"

        if access is None:
            problems.append(f"{where}: no access declared (use @public, @authenticated or @needs)")
        elif access == PUBLIC and route.path not in ALLOWED_PUBLIC_PATHS:
            problems.append(f"{where}: declared public but is not on the public list")
        elif access not in {PUBLIC, "authenticated"} and access not in CODES:
            problems.append(f"{where}: unknown permission {access!r}")

    if problems:
        raise RouteProtectionError("Route protection check failed:\n  " + "\n  ".join(problems))
