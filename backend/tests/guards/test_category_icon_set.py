"""The category icons: the server's list (finode/category_icons.py) and the app's drawings
(frontend/src/components/category-icons.json) name the same icons in the same groups."""

import json
from pathlib import Path

import pytest

from finode.category_icons import CHOOSABLE, DEFAULT, GROUPS, SYSTEM, UNCATEGORISED, check_icon

ROOT = Path(__file__).resolve().parents[3]


def test_server_and_app_sets_are_the_same():
    app = json.loads((ROOT / "frontend/src/components/category-icons.json").read_text())
    assert [(g["name"], tuple(g["icons"])) for g in app["groups"]] == list(GROUPS)
    assert set(app["system"]) == SYSTEM
    assert set(app["paths"]) == CHOOSABLE | SYSTEM
    assert not CHOOSABLE & SYSTEM and DEFAULT in CHOOSABLE and UNCATEGORISED in SYSTEM


def test_check_icon():
    assert check_icon("tag") == "tag"
    for bad in ("rocket", "layers", ""):
        with pytest.raises(ValueError, match=f"'{bad}' is not one of finode's category icons"):
            check_icon(bad)
