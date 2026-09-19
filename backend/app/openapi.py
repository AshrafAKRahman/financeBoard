"""Dump the API's OpenAPI schema to a file.

The frontend's client types are generated from this, so the schema has to be obtainable
without a running server or a database:

    uv run python -m app.openapi /tmp/openapi.json
"""

import json
import sys
from pathlib import Path

import app.models
from app.main import app


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.openapi <path>", file=sys.stderr)
        return 2
    Path(argv[1]).write_text(json.dumps(app.openapi(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
