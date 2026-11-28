"""Look A (the owner's choice, 2026-11-24): a page's hero, its figure and what explains it, is the page's one card; the
lists under it are plain, on the page itself. A page with no hero has no card at all."""

from calendar import monthrange
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

from finode.clock import local_today

from ..books import leg
from .conftest import Api

# The boxes drawn in the surface colour with round corners, outside what one taps (chips, pills, buttons, rows) and
# what opens over the page (a closed menu's panel included).
CARDS = """() => {
  const probe = document.createElement('div');
  probe.style.background = 'var(--surface)';
  document.body.append(probe);
  const surface = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return [...document.querySelectorAll('main *')].filter(e => {
    if (e.closest('button, a, input, select, textarea, label, [role=radiogroup], [role=dialog], details > summary')) return false;
    const s = getComputedStyle(e);
    return s.backgroundColor === surface && parseFloat(s.borderTopLeftRadius) > 0
      && e.checkVisibility({ contentVisibilityAuto: true, opacityProperty: true, visibilityProperty: true });
  }).map(e => e.textContent.trim().slice(0, 60));
}"""


@pytest.fixture
def filled(api: Api, books):
    """An entry today, one dated ahead, a person who owes, and a pinned account, so every page shows its hero."""
    today = local_today()
    api.post(
        "/transactions/",
        date=today.isoformat(),
        payee="Market",
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
    )
    api.post(
        "/transactions/",
        date=ahead(today).isoformat(),
        payee="Landlord",
        postings=[leg(books["rent"], "debit", "900"), leg(books["checking"], "credit", "900")],
    )
    who = api.post("/contacts/", name="Alice")
    api.post(
        f"/contacts/{who['id']}/transfers",
        direction="sent",
        purpose="loan",
        amount="500",
        account_id=books["checking"]["id"],
    )
    return {**books, "alice": who}


def month_end(today: date) -> date:
    return today.replace(day=monthrange(today.year, today.month)[1])


def ahead(today: date) -> date:
    """A day dated ahead that Coming up shows: it looks from tomorrow to the end of this month."""
    return min(today + timedelta(days=3), max(month_end(today), today + timedelta(days=1)))


def hero_pages(filled: dict) -> list[str]:
    today = local_today()
    # On a month's last day Coming up has nothing to show (it looks no further than today), so it has no hero.
    coming_up = ["/budget/coming-up"] if today < month_end(today) else []
    return [
        "/",
        "/budget",
        *coming_up,
        "/categories",
        f"/categories/{filled['food']['id']}",
        "/accounts",
        f"/accounts/{filled['checking']['id']}",
        "/people",
        f"/people/{filled['alice']['id']}",
    ]


def test_the_hero_is_the_one_card_on_every_page_that_has_one(signed_in_page: Page, filled):
    page = signed_in_page
    for path in hero_pages(filled):
        page.goto(path)
        expect(page.locator("main h1").first).to_be_attached()
        page.wait_for_load_state("networkidle")
        cards = page.evaluate(CARDS)
        assert len(cards) == 1, f"{path}: one card, the hero; found {cards}"


@pytest.mark.parametrize("path", ["/transactions", "/recurring", "/tags"])
def test_a_page_with_no_hero_has_no_card(signed_in_page: Page, filled, path: str):
    page = signed_in_page
    page.goto(path)
    expect(page.locator("main h1").first).to_be_attached()
    page.wait_for_load_state("networkidle")
    assert page.evaluate(CARDS) == [], path


def test_the_accounts_hero_says_what_is_held_and_what_is_owed_on_cards_apart(signed_in_page: Page, api: Api, filled):
    page = signed_in_page
    api.post("/accounts/", name="Amex", type="liabilities.cards", balance="300")
    page.goto("/accounts")
    hero = page.get_by_test_id("accounts-hero")
    expect(hero).to_contain_text("In your accounts")
    expect(hero).to_contain_text("4,460.00")  # Checking: 5,000 less the market's 40 and Alice's 500
    expect(hero).to_contain_text("300.00 owed on cards")
