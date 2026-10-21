"""The Save section on the budget page, the sheet over it, and the switch on the account's forms."""

from .test_budget import account, assign, move
from .test_plan_save import books, saving  # noqa: F401  (the fixture)


def page(client, tab=""):
    return client.get(f"/plan{'?tab=' + tab if tab else ''}").text


def test_the_page_has_spend_and_save_chips_and_spend_is_the_default(client, books):
    text = page(client)
    assert 'aria-pressed="true">Spend<' in text and 'aria-pressed="false">Build<' in text
    assert "&tab=build" in text and "data-budget-tree" in text and "data-budget-saving" not in text
    assert "Mutual Funds" not in text, "a Save line is not in the Spend list"


def test_the_save_chip_lists_the_accounts_planned_for_saving(client, books):
    assign(client, books["fund"], "15000")
    move(client, books["bank"], books["fund"], "5000")
    text = " ".join(page(client, "build").split())
    assert 'aria-pressed="true">Build<' in text and "data-budget-saving" in text and "data-budget-tree" not in text
    assert "Mutual Funds" in text and "moved 5,000.00 this month" in text and "10,000.00" in text, "what is still to move"
    assert "Left to build" in text, "the sum behind Ready to assign shows the new row"


def test_a_book_without_saving_shows_no_extra_row_and_an_invitation(client, root_accounts):
    account(client, root_accounts, "Bank", "Assets", balance="100")
    assert "Left to build" not in page(client)
    empty = page(client, "build")
    assert "Plan under Build" in empty and "data-budget-saving" not in empty


def test_the_sheet_over_a_save_line_assigns_and_stays_on_save(client, books):
    sheet = client.get(f"/plan/category/{books['fund']['aid']}/sheet").text
    assert "Moved in" in sheet and "to move" in sheet and 'name="tab" value="build"' in sheet
    answered = client.post("/plan/assign", data={"category": books["fund"]["aid"], "amount": "300", "sheet": "1", "tab": "build"})
    assert answered.status_code == 200 and "data-budget-saving" in answered.text and "data-budget-tree" not in answered.text
    assert saving(client.get("/api/budget/").json())["assigned"] == "300.00"
    spend = client.post("/plan/assign", data={"category": books["food"]["aid"], "amount": "100", "sheet": "1"})
    assert "data-budget-tree" in spend.text, "the default is still Spend"


def test_the_move_page_offers_save_lines(client, books):
    text = client.get("/plan/move").text
    assert "Mutual Funds" in text and "Food" in text


def test_the_edit_page_offers_plan_for_saving_only_outside_the_budget_under_assets(client, books):
    edit = client.get(f"/accounts/{books['fund']['aid']}/edit").text
    assert 'name="saving" value="1" checked' in edit and "Plan under Build" in edit
    loan = account(client, books["roots"], "Loan", "Liabilities", on_budget=False)
    assert 'data-saving hidden' not in client.get(f"/accounts/{loan['aid']}/edit").text, "a loan can be paid down under Build too"
    bank = client.get(f"/accounts/{books['bank']['aid']}/edit").text
    assert 'data-saving hidden' in bank, "an account in the budget is not planned for saving"


def test_the_edit_form_switches_saving_on_and_off_and_clears_the_payment_category(client, books):
    sip = account(client, books["roots"], "Recurring", "Assets", on_budget=False)
    saved = client.post(f"/accounts/{sip['aid']}/edit", data={"name": "Recurring", "budget_choice": "1", "saving": "1"})
    assert saved.status_code == 200 and saved.headers["HX-Redirect"].startswith("/accounts/")
    assert client.get(f"/api/accounts/{sip['aid']}").json()["saving"] is True
    client.post(f"/accounts/{sip['aid']}/edit", data={"name": "Recurring", "budget_choice": "1"})
    assert client.get(f"/api/accounts/{sip['aid']}").json()["saving"] is False
    joined = client.post(f"/accounts/{sip['aid']}/edit", data={"name": "Recurring", "budget_choice": "1", "saving": "1", "on_budget": "1"})
    assert client.get(f"/api/accounts/{sip['aid']}").json()["saving"] is False, "in the budget wins: nothing is both"
    assert joined.status_code == 200


def test_the_new_account_form_can_make_a_saving_account(client, root_accounts):
    made = client.post("/accounts", data={"name": "FD", "parent_id": root_accounts["Assets"], "budget_choice": "1", "saving": "1"})
    assert made.status_code == 200
    fd = next(a for a in client.get("/api/accounts/").json() if a["name"] == "FD")
    assert fd["saving"] is True and fd["on_budget"] is False
