"""The sliders button on the Plan: which sections the Plan has, and which accounts are in Build."""

from .test_budget import account, budget


def page(client, tab=""):
    return client.get(f"/plan{'?tab=' + tab if tab else ''}").text


def configure(client, **form):
    return client.post("/plan/configure", data={"month": "2026-10", "tab": "spend", **form})


def test_the_page_has_the_button_and_the_sheet_lists_only_the_three_sections(client, root_accounts):
    account(client, root_accounts, "Bank", "Assets", balance="1000")
    account(client, root_accounts, "Mutual Funds", "Assets", on_budget=False, saving=True)
    text = page(client)
    assert "/plan/configure" in text and 'id="plan-sheet-body"' in text
    sheet = client.get("/plan/configure?month=2026-10").text
    assert "Your plan" in sheet and 'name="build" value="1" checked' in sheet and 'name="earn"' in sheet
    assert "Spend" in sheet and "Mutual Funds" not in sheet and 'name="saving"' not in sheet, "no list of accounts"


def test_turning_a_section_off_hides_its_chip_and_keeps_the_data(client, root_accounts):
    fund = account(client, root_accounts, "Mutual Funds", "Assets", on_budget=False, saving=True)
    account(client, root_accounts, "Bank", "Assets", balance="1000")
    client.put(f"/api/budget/categories/{fund['aid']}", json={"amount": "300"})
    answered = configure(client, tab="build", earn="1")  # Build off, Earn on
    assert answered.status_code == 200 and answered.headers["HX-Redirect"] == "/plan?month=2026-10&tab=spend", "its tab is gone"
    text = page(client)
    assert ">Build<" not in text and ">Earn<" in text
    assert budget(client)["saving"][0]["assigned"] == "300.00", "the plan is still there"
    assert client.get("/api/accounts/").json() and next(a for a in client.get("/api/accounts/").json() if a["name"] == "Mutual Funds")["saving"] is True
    back = configure(client, build="1")
    assert back.status_code == 200 and ">Build<" in page(client)


def test_only_spend_leaves_a_button_and_no_chips(client, root_accounts):
    account(client, root_accounts, "Bank", "Assets", balance="1000")
    account(client, root_accounts, "Food", "Expenses")
    configure(client)  # both off
    text = page(client)
    assert "/plan/configure" in text and "cat-chips" in text and ">Build<" not in text and ">Earn<" not in text
    assert "data-budget-tree" in text


def test_it_is_gone_when_the_plan_is_switched_off(client, root_accounts, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "plan_enabled", False)
    assert "/plan/configure" not in page(client)
    assert client.get("/plan/configure").status_code == 404
    assert configure(client, build="1").status_code == 404


def test_the_choice_is_in_the_backup_and_comes_back(client, root_accounts):
    configure(client, earn="1")  # Build off, Earn on
    doc = client.get("/api/backup").json()
    assert doc["profile"]["plan_build"] is False and doc["profile"]["plan_earn"] is True
    profile = client.get("/api/profile/").json()
    assert profile["plan_build"] is False and profile["plan_earn"] is True
