"""The app's icons: frontend/src/components/icons.json is their one source (components/Icon draws them, and TypeScript
refuses a name it does not hold). The markup is put into the page as it is, so it must be plain SVG drawing only."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = json.loads((ROOT / "frontend" / "src" / "components" / "icons.json").read_text())
DRAWING = {"path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "g"}


def test_every_icon_is_plain_svg_drawing():
    assert ICONS and all(isinstance(name, str) and isinstance(markup, str) for name, markup in ICONS.items())
    for name, markup in ICONS.items():
        tags = set(re.findall(r"<\s*([a-zA-Z]+)", markup))
        assert tags and tags <= DRAWING, (name, tags - DRAWING)
        assert not re.search(r"\son[a-z]+\s*=|javascript:|<\s*script", markup, re.I), name


def test_the_icons_the_layout_and_the_home_screen_use_are_there():
    for name in ("home", "budget", "plus", "bell", "gear", "back", "close", "trash", "robot"):
        assert name in ICONS, name
    for asset in ("favicon.svg", "apple-touch-icon.png"):
        assert (ROOT / "frontend" / "public" / asset).is_file(), asset
