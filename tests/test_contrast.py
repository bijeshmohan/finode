"""The quiet grey carries every second line and hint, so it must be readable: 4.5 : 1 on the page and the tiles."""

import re
from pathlib import Path

CSS = (Path(__file__).parent.parent / "app" / "static" / "tokens.css").read_text()


def tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block))


def luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_muted_text_is_readable_in_both_themes():
    light = tokens(CSS.split(":root {", 1)[1].split("}", 1)[0])
    dark = tokens(CSS.split(':root[data-theme="dark"] {', 1)[1].split("}", 1)[0])
    for name, theme in (("light", light), ("dark", dark)):
        for ground in ("bg", "surface"):
            assert ratio(theme["muted"], theme[ground]) >= 4.5, f"{name}: muted on {ground}"
    assert ratio(light["muted"], light["surface-2"]) >= 4.5, "also on a grey chip"
    assert ratio(light["faint"], light["bg"]) >= 3.5, "the faint grey is for placeholders and glyphs"
