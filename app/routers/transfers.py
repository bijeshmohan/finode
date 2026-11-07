from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Transfers
from ..schemas.contact import TransferRead
from ..services.contact_errors import ConflictError

router = APIRouter(prefix="/transfers", tags=["contacts"], dependencies=[Depends(require_authenticated_user)])


@router.get("/{transaction_id}", response_model=TransferRead)
def get_transfer(transaction_id: UUID, transfers: Transfers):
    try:
        return transfers.read(transaction_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="transfer not found!") from None


@router.delete("/{transaction_id}", status_code=204)
def reverse_transfer(transaction_id: UUID, transfers: Transfers):
    """Undo a transfer for good: its entry, what it left owed and its activity go. Refused (409) once anything was
    settled against what it left owed; reverse that settlement first."""
    try:
        transfers.reverse(transaction_id)
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except ValueError:
        raise HTTPException(status_code=404, detail="transfer not found!") from None
