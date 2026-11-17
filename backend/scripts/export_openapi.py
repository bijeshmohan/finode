"""Write the JSON API's OpenAPI schema to frontend/openapi.json, from which the React app's types are generated.

Run through `npm --prefix frontend run gen:api`; tests/api/test_openapi_file.py fails when the file is out of date.
"""

import json
from pathlib import Path
from typing import Any

from finode.main import app

TARGET = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def schema() -> dict[str, Any]:
    """The schema FastAPI serves at /openapi.json (served only with FINODE_API_DOCS, built here either way)."""
    return app.openapi()


if __name__ == "__main__":
    TARGET.write_text(json.dumps(schema(), indent=2, sort_keys=True) + "\n")
