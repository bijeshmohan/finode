"""The React app draws the web pages' icons: frontend/src/components/icons.json holds exactly what
partials/icons.html draws, so the two UIs cannot drift apart while both exist."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def web_icons() -> dict[str, str]:
    """Each `name == "…"` branch of the icon macro and the SVG markup inside it, whitespace collapsed."""
    macro = (ROOT / "app" / "templates" / "partials" / "icons.html").read_text()
    parts = re.split(r'\{%-?\s*(?:el)?if name == "([a-z0-9-]+)"\s*-?%\}', macro)
    icons = {}
    for name, body in zip(parts[1::2], parts[2::2], strict=True):
        markup = re.split(r"\{%-?\s*(?:endif|else)", body)[0]
        icons[name] = " ".join(markup.split())
    return icons


def test_the_react_icons_are_the_web_icons():
    react = json.loads((ROOT / "frontend" / "src" / "components" / "icons.json").read_text())
    assert react == web_icons(), "regenerate frontend/src/components/icons.json from partials/icons.html"


def test_the_react_app_has_the_web_app_icons():
    for name in ("favicon.svg", "apple-touch-icon.png"):
        web = (ROOT / "app" / "static" / name).read_bytes()
        assert (ROOT / "frontend" / "public" / name).read_bytes() == web, f"copy app/static/{name} to frontend/public"
