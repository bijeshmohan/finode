"""The switcher's page transition is plain CSS; these keep its parts together."""

from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "app" / "static" / "style.css").read_text()


def test_the_chosen_chip_glides_and_the_content_rises():
    assert "@view-transition { navigation: auto; }" in CSS
    assert "view-transition-name: switch-pill" in CSS
    assert "main > :not(.page-head):not(.cat-bar) { animation: rise-in" in CSS


def test_reduced_motion_turns_every_part_off():
    block = CSS[CSS.rindex("prefers-reduced-motion: reduce"):]
    assert "navigation: none" in block and "animation: none" in block
