"""What is coming up for the budget: entries dated after today and the occurrences recurring rules will record, up to a day.

Both are shown the same way. Nothing is stored: an entry is read from the books, an occurrence is worked out from its rule
(`schedule`), so the list is always what the rules and the books say now."""

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from ..clock import local_today
from ..models.transaction import PostingSide
from ..schemas.coming_up import ComingUpItem, ComingUpLine, ComingUpRead
from ..schemas.recurring import RecurringPostingData
from ..schemas.transaction import PostingBase, PostingCreate
from . import schedule
from .account import AccountService
from .budget import BudgetError, month_end
from .recurring import RecurringService
from .transaction import TransactionService

MAX_ENTRIES = 200
MAX_PER_RULE = 100
MAX_DAYS_AHEAD = 366


class ComingUpService:
    def __init__(self, accounts: AccountService, transactions: TransactionService, recurring: RecurringService):
        self.accounts = accounts
        self.transactions = transactions
        self.recurring = recurring

    def view(self, through: date | None = None) -> ComingUpRead:
        today = local_today()
        through = through or month_end(today)
        if through > today + timedelta(days=MAX_DAYS_AHEAD):
            raise BudgetError(f"look at most {MAX_DAYS_AHEAD} days ahead!")
        accounts = self.accounts.ar.list()
        by_id = {a.id: a for a in accounts}
        in_budget = {a.id for a in accounts if a.on_budget}
        roots = {a.id: AccountService.root_name(a, by_id) for a in accounts}
        items: list[ComingUpItem] = []

        def item(
            day: date,
            payee: str | None,
            debits: list[ComingUpLine],
            credits: list[ComingUpLine],
            amount: Decimal,
            **ids: UUID | None,
        ) -> None:
            if not any(line.account_id in in_budget for line in debits + credits):
                return  # nothing here touches the budget's accounts
            income = any(roots.get(line.account_id) == "Income" for line in credits)
            items.append(
                ComingUpItem(date=day, payee=payee, amount=amount, income=income, debits=debits, credits=credits, **ids)
            )

        def lines(
            postings: Iterable[PostingBase | PostingCreate | RecurringPostingData], side: PostingSide
        ) -> list[ComingUpLine]:
            return [
                ComingUpLine(account_id=p.account_id, category_id=p.category_id)
                for p in postings
                if p.side == side and p.account_id is not None
            ]

        if through > today:
            for t in self.transactions.list(None, today + timedelta(days=1), through, MAX_ENTRIES, 0):
                amount = sum((p.amount for p in t.postings if p.side == PostingSide.DEBIT), Decimal(0))
                item(
                    t.date,
                    t.payee,
                    lines(t.postings, PostingSide.DEBIT),
                    lines(t.postings, PostingSide.CREDIT),
                    amount,
                    transaction_id=t.id,
                )
            for rule in self.recurring.list():
                if not rule.active:
                    continue
                if rule.postings:
                    debits, credits = lines(rule.postings, PostingSide.DEBIT), lines(rule.postings, PostingSide.CREDIT)
                    amount = sum((p.amount for p in rule.postings if p.side == PostingSide.DEBIT), Decimal(0))
                elif rule.from_account_id and rule.to_account_id and rule.amount is not None:
                    debits = [ComingUpLine(account_id=rule.to_account_id, category_id=rule.category_id)]
                    credits = [ComingUpLine(account_id=rule.from_account_id, category_id=rule.category_id)]
                    amount = rule.amount
                else:
                    continue
                # A rule that is behind (not caught up yet, or held by a problem) carries on with its own days.
                tomorrow = today + timedelta(days=1)
                day = max(
                    rule.next_date, schedule.first_on_or_after(rule.start_date, rule.frequency, rule.every, tomorrow)
                )
                found = 0
                while day <= through and (rule.end_date is None or day <= rule.end_date) and found < MAX_PER_RULE:
                    item(day, rule.payee, debits, credits, amount, recurring_id=rule.id)
                    day = schedule.first_after(rule.start_date, rule.frequency, rule.every, day)
                    found += 1
        items.sort(key=lambda i: (i.date, (i.payee or "").casefold()))
        directions = {i.income for i in items}
        total = sum((i.amount for i in items), Decimal(0)) if len(directions) == 1 else None
        return ComingUpRead(through=through, count=len(items), total=total, items=items)
