"""The switcher's page transition is plain CSS; these keep its parts together."""

from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "app" / "static" / "style.css").read_text()


def test_the_chosen_chip_glides_and_the_content_rises():
    assert "@view-transition { navigation: auto; }" in CSS
    assert "view-transition-name: switch-pill" in CSS
    assert "main > :not(.page-head):not(.cat-bar) { animation: rise-in" in CSS


def test_reduced_motion_turns_every_part_off():
    block = next(b for b in CSS.split("@media (prefers-reduced-motion: reduce)") if "navigation: none" in b)
    assert "navigation: none" in block and "animation: none" in block


def test_sheets_slide_up_and_the_toast_comes_and_goes():
    assert "@starting-style { dialog.sheet[open]" in CSS and "dialog.sheet::backdrop { opacity: 0" in CSS
    assert "dialog.sheet.sheet-bottom { opacity: 1; transform: translateY(100%); }" in CSS
    assert "animation: toast-in .25s ease-out, toast-out .3s ease-in var(--toast-life) forwards" in CSS
    assert "dialog.sheet, dialog.sheet::backdrop { transition: none; }" in CSS
