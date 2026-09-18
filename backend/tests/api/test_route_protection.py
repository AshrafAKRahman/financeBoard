"""No route ships without saying what it needs (R7.AC1, R7.AC2, R7.AC5)."""

import pytest
from fastapi import APIRouter, FastAPI

from app.api.protection import (
    ALLOWED_PUBLIC_PATHS,
    PUBLIC,
    RouteProtectionError,
    authenticated,
    check_routes,
    declared_access,
    iter_api_routes,
    needs,
    public,
)
from app.main import app
from app.platform.access.permissions import CODES


def test_every_route_in_the_app_declares_its_access() -> None:
    """R7.AC1"""
    undeclared = [
        f"{sorted(route.methods)} {route.path}"
        for route in iter_api_routes(app)
        if declared_access(route) is None
    ]
    assert undeclared == []


def test_declared_permissions_all_exist_in_the_catalogue() -> None:
    unknown = {
        declared_access(route)
        for route in iter_api_routes(app)
        if declared_access(route) not in {PUBLIC, "authenticated"}
    } - set(CODES)
    assert unknown == set()


def test_only_the_expected_routes_are_public() -> None:
    """R7.AC5 — sign-in, the invitation link, and health."""
    public_paths = {
        route.path for route in iter_api_routes(app) if declared_access(route) == PUBLIC
    }
    assert public_paths <= ALLOWED_PUBLIC_PATHS
    assert "/api/v1/health" in public_paths
    assert "/api/v1/auth/login" in public_paths


def test_the_real_app_passes_its_own_check() -> None:
    check_routes(app)


def test_an_undeclared_route_stops_start_up() -> None:
    """R7.AC2 — the failure mode that matters: someone forgets the decorator."""
    sample = FastAPI()
    router = APIRouter()

    @router.get("/api/v1/oops")
    def forgotten() -> dict:
        return {}

    sample.include_router(router)

    with pytest.raises(RouteProtectionError) as error:
        check_routes(sample)
    assert "/api/v1/oops" in str(error.value)
    assert "no access declared" in str(error.value)


def test_an_unknown_permission_stops_start_up() -> None:
    sample = FastAPI()

    @sample.get("/api/v1/typo")
    @needs("invoicce:post")
    def typo() -> dict:
        return {}

    with pytest.raises(RouteProtectionError) as error:
        check_routes(sample)
    assert "unknown permission" in str(error.value)


def test_an_unexpected_public_route_stops_start_up() -> None:
    sample = FastAPI()

    @sample.get("/api/v1/secrets")
    @public
    def wide_open() -> dict:
        return {}

    with pytest.raises(RouteProtectionError) as error:
        check_routes(sample)
    assert "not on the public list" in str(error.value)


def test_a_properly_declared_route_passes() -> None:
    sample = FastAPI()

    @sample.get("/api/v1/fine")
    @authenticated
    def fine() -> dict:
        return {}

    @sample.get("/api/v1/also-fine")
    @needs("user:read")
    def also_fine() -> dict:
        return {}

    check_routes(sample)
