"""Serving the built web application from the API's own origin (R10.AC3, decision D16).

The session cookie is `HttpOnly; SameSite=Lax`, so a browser will not send it on a
cross-origin request. The application must therefore be served by the API itself rather
than from a separate host: one origin, no CORS, and the cookie works as intended.

In development `frontend/dist` does not exist and Vite serves the assets instead, so this
mounts nothing and the API behaves exactly as it did before.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from app.api.protection import public

# backend/app/api/spa.py → the repository root → frontend/dist
DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

# Hashed filenames are immutable; the entry document never is, or a deploy would not be seen.
IMMUTABLE = "public, max-age=31536000, immutable"
NEVER = "no-cache"


class HashedAssets(StaticFiles):
    """Static files, told apart by whether their name carries a content hash."""

    def file_response(self, *args: object, **kwargs: object) -> Response:
        response = super().file_response(*args, **kwargs)  # type: ignore[arg-type]
        response.headers["Cache-Control"] = IMMUTABLE
        return response


def mount_web_application(application: FastAPI, dist: Path = DIST) -> bool:
    """Serve `dist` under the API's origin. Returns whether there was anything to serve."""
    index = dist / "index.html"
    if not index.is_file():
        return False

    assets = dist / "assets"
    if assets.is_dir():
        application.mount("/assets", HashedAssets(directory=assets), name="assets")

    @application.get("/{path:path}", include_in_schema=False)
    @public
    def web_application(request: Request, path: str) -> Response:
        # An unknown /api path is a missing endpoint, not a page: answering it with the
        # application's HTML would turn a 404 into a parse error in the caller.
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # A file that exists is served as itself; anything else is a route the browser owns,
        # so the application's entry document answers and React Router reads the path.
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate, headers={"Cache-Control": NEVER})

        return FileResponse(index, headers={"Cache-Control": NEVER})

    return True
