"""What needs the person's decision now: payments no category took, accounts left out of the budget, recurring rules
that cannot be recorded, card bills that are due soon or overdue. Everything is worked out from the books on the spot; nothing is stored."""

from ..schemas.todo import TodoCard, TodoRead, TodoRule
from .account import AccountService
from .budget import BudgetService
from .recurring import RecurringService


class TodoService:
    def __init__(self, budget: BudgetService, recurring: RecurringService, accounts: AccountService):
        self.budget = budget
        self.accounts = accounts
        self.recurring = recurring

    def read(self) -> TodoRead:
        view = self.budget.view()
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
        count = (1 if view.uncategorised else 0) + len(view.left_out_accounts) + len(rules) + len(bills)
        return TodoRead(
            uncategorised=view.uncategorised,
            left_out_accounts=view.left_out_accounts,
            failing_rules=rules,
            card_bills=bills,
            count=count,
        )
