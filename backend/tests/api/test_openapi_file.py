"""The React app's API types are generated from frontend/openapi.json, which must match the API as it is now."""

import json

from scripts import export_openapi
from tests.paths import FRONTEND

SCHEMA_FILE = FRONTEND / "openapi.json"


def test_the_frontend_schema_is_up_to_date():
    assert json.loads(SCHEMA_FILE.read_text()) == export_openapi.schema(), "run: npm --prefix frontend run gen:api"
