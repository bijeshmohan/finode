"""What needs the person's decision now: payments no category took, accounts left out of the budget, recurring rules
that cannot be recorded. Everything is worked out from the books on the spot; nothing is stored."""

from ..schemas.todo import TodoRead, TodoRule
from .budget import BudgetService
from .recurring import RecurringService


class TodoService:
    def __init__(self, budget: BudgetService, recurring: RecurringService):
        self.budget = budget
        self.recurring = recurring

    def read(self) -> TodoRead:
        view = self.budget.view()
        rules = [
            TodoRule(rid=r.rid, name=r.payee or "A recurring transaction", error=r.last_error)
            for r in self.recurring.list()
            if r.active and r.last_error
        ]
        count = (1 if view.uncategorised else 0) + len(view.left_out_accounts) + len(rules)
        return TodoRead(
            uncategorised=view.uncategorised,
            left_out_accounts=view.left_out_accounts,
            failing_rules=rules,
            count=count,
        )
