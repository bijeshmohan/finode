"""Guards on the app's look that live in its CSS (frontend/src), carried over from the old pages' guards (step 10):
colours defined once, the logo in the ink palette, one bar height, no chart colours, and no rule that blanks every
checkbox and radio on iOS."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
TOKENS = (SRC / "styles" / "tokens.css").read_text()
SHEETS = {p: p.read_text() for p in SRC.rglob("*.css") if p.name != "tokens.css"}


def rule(sheet: str, selector: str) -> str:
    start = sheet.index(f"\n{selector} {{") + 1
    return sheet[start : sheet.index("}", start)]


def test_the_colours_live_in_one_file_with_both_dark_blocks():
    for block in (":root {", "@media (prefers-color-scheme: dark)", ':root[data-theme="dark"]'):
        assert block in TOKENS, block
    for path, sheet in SHEETS.items():
        for token in ("--bg:", "--surface:", "--accent:", "--text:", "--muted:"):
            assert token not in sheet, f"{token} is defined in {path.name}: it belongs in tokens.css"


def test_the_logo_follows_the_ink_palette_in_light_and_dark():
    svg = (SRC.parent / "public" / "favicon.svg").read_text()
    assert "#2563eb" not in svg and "prefers-color-scheme:dark" in svg.replace(" ", "")


def test_every_progress_bar_takes_its_thickness_from_one_token():
    assert "--bar-h: 3px" in TOKENS
    budget = (SRC / "features" / "budget" / "Budget.module.css").read_text()
    home = (SRC / "features" / "home" / "Home.module.css").read_text()
    for sheet, selector in ((budget, ".bar"), (budget, ".glanceBar"), (home, ".glanceBar")):
        assert "height: var(--bar-h)" in rule(sheet, selector), selector


def test_no_share_bars_and_no_chart_colours():
    for path, sheet in SHEETS.items():
        assert "--chart-" not in sheet and ".sharebar" not in sheet and ".cdot" not in sheet, path.name


def test_no_rule_blanks_every_checkbox_and_radio_on_ios():
    """`appearance: none` on every input blanks checkboxes and radios in Safari on iOS; it belongs on a class only."""
    for path, sheet in SHEETS.items():
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
            bare = [s.strip() for s in selectors.split(",") if re.fullmatch(r"input(\[[^\]]*\])?", s.strip())]
            assert not (bare and "appearance: none" in body), (path.name, bare)
