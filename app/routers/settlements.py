from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Settlements
from ..schemas.contact import SettlementRead
from ..services.contact_errors import ConflictError

router = APIRouter(prefix="/settlements", tags=["contacts"], dependencies=[Depends(require_authenticated_user)])


@router.get("/{transaction_id}", response_model=SettlementRead)
def get_settlement(transaction_id: UUID, settlements: Settlements):
    try:
        return settlements.read(transaction_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="settlement not found!") from None


@router.delete("/{transaction_id}", status_code=204)
def reverse_settlement(transaction_id: UUID, settlements: Settlements):
    """Undo a settlement for good: what it cleared is owed again. Refused (409) once what its excess left owed has been
    settled in turn."""
    try:
        settlements.reverse(transaction_id)
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except ValueError:
        raise HTTPException(status_code=404, detail="settlement not found!") from None
