"""docs/developer/api.md lists every JSON API route (so the document cannot drift from the code)."""

from pathlib import Path

from fastapi.routing import APIRoute

from app.main import app

DOC = (Path(__file__).resolve().parent.parent / "docs" / "developer" / "api.md").read_text()


def test_every_api_route_is_in_the_api_document():
    missing = []
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/"):
            for method in route.methods - {"HEAD"}:
                row = f"| `{method}` | `{route.path.removeprefix('/api')}` |"
                if row not in DOC:
                    missing.append(row)
    assert not missing, "add these to docs/developer/api.md:\n" + "\n".join(sorted(missing))
