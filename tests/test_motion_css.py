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


def test_bars_fill_once_folds_ease_and_presses_answer():
    assert "html:not([data-live]) .glance-bar i" in CSS and "@keyframes bar-fill" in CSS
    assert "details.upcoming::details-content" in CSS and "interpolate-size: allow-keywords" in CSS
    assert "a.tx:active" in CSS and "a.crow:active" in CSS
    assert 'dataset.live = "1"' in (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text()


def test_a_sheets_content_fades_over_its_placeholders_and_the_saved_row_settles():
    assert "#txn-sheet-body > *, #cat-sheet-body > * { animation: fade-in" in CSS
    assert "a.tx.tx-new { animation: tx-new" in CSS


def test_the_info_button_is_only_highlighted_while_open_or_hovered_with_a_real_pointer():
    assert "@media (hover: hover) { .info-button:hover" in CSS, "a tap on a phone must not leave the button grey"
    assert "details[open].calc-info > summary" in CSS
