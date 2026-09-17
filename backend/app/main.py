from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import pooled_engine

app = FastAPI(title="Finance ERP", version="0.1.0")


@app.get("/api/v1/health")
def health() -> JSONResponse:
    try:
        with pooled_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "degraded", "database": "unreachable"}, status_code=503)
    return JSONResponse({"status": "ok", "database": "ok"})
