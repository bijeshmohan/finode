"""Checkboxes, radios, fieldsets and copy buttons that Safari on iOS drew badly or could not use."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

CSS = (Path(__file__).parent.parent / "app" / "static" / "style.css").read_text()


def test_checkboxes_and_radios_keep_their_native_look_and_a_thumb_sized_target():
    """`appearance: none` on every input blanks them on iOS: they must be put back after that rule."""
    rule = re.search(r'input\[type="checkbox"\], input\[type="radio"\] \{(.*?)\}', CSS, re.S).group(1)
    assert "appearance: auto" in rule and "accent-color" in rule
    assert CSS.index("appearance: none") < CSS.index('input[type="checkbox"]')
    assert "min-height: 0" in rule and "width: 1.5rem" in rule


def test_fieldsets_stay_block_for_safari():
    assert re.search(r"fieldset\.plain \{ display: block", CSS)


def test_the_budget_checkbox_is_a_whole_tappable_row(client: TestClient, root_accounts):
    bank = client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    page = client.get(f"/accounts/{bank['aid']}/edit").text
    assert '<label class="check">' in page and 'type="checkbox" name="on_budget"' in page
    assert "label.check" in CSS and "cursor: pointer" in CSS


def test_the_token_form_wraps_its_cards_so_the_legend_is_not_a_grid_item(client: TestClient):
    page = client.get("/profile/assistants").text
    form = page[page.index('<fieldset class="plain">'):]
    assert form.index("<legend>Access</legend>") < form.index('<div class="access-choice">')
    assert page.count('type="radio" name="scope"') == 2


def test_a_new_token_can_be_copied_with_one_tap(client: TestClient):
    created = client.post("/profile/assistants", data={"name": "Phone", "scope": "read"})
    assert created.status_code == 200
    assert 'data-copy="#token-secret"' in created.text and "Copy token" in created.text
    assert 'id="token-secret"' in created.text


def test_the_copy_script_falls_back_when_the_clipboard_is_refused():
    js = (Path(__file__).parent.parent / "app" / "static" / "app.js").read_text()
    assert "execCommand" in js and "isSecureContext" in js and "new-token" in js
