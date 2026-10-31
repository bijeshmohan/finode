from fastapi import APIRouter, Depends

from ..auth import require_authenticated_user
from ..dependencies import Todo
from ..schemas.todo import TodoRead

router = APIRouter(
    prefix="/todo",
    tags=["todo"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/", response_model=TodoRead, status_code=200)
def get_todo(todo: Todo):
    """What needs a decision now: payments no category took, accounts left out of the budget, failing recurring rules."""
    return todo.read()
