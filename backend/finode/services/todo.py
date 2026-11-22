"""What needs the person's decision now: recurring rules that cannot be recorded, card bills that are due soon or overdue. Everything is worked out from the books on the spot; nothing is stored."""

from ..schemas.todo import TodoCard, TodoRead, TodoRule
from .account import AccountService
from .recurring import RecurringService


class TodoService:
    def __init__(self, recurring: RecurringService, accounts: AccountService):
        self.accounts = accounts
        self.recurring = recurring

    def read(self) -> TodoRead:
        rules = [
            TodoRule(recurring_id=r.id, name=r.payee or "A recurring transaction", error=r.last_error)
            for r in self.recurring.list()
            if r.active and r.last_error
        ]
        bills = [
            TodoCard(
                account_id=bill.account_id,
                path=path,
                bill=bill.bill,
                due_date=bill.due_date,
                days_to_due=bill.days_to_due,
            )
            for path, bill in self.accounts.bills_due()
        ]
        return TodoRead(
            failing_rules=rules,
            card_bills=bills,
            count=len(rules) + len(bills),
        )
