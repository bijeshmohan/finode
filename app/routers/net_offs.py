from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import NetOffs
from ..schemas.contact import NetOffRead

router = APIRouter(prefix="/net-offs", tags=["contacts"], dependencies=[Depends(require_authenticated_user)])


@router.get("/{transaction_id}", response_model=NetOffRead)
def get_net_off(transaction_id: UUID, net_offs: NetOffs):
    try:
        return net_offs.read(transaction_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="net off not found!") from None


@router.delete("/{transaction_id}", status_code=204)
def reverse_net_off(transaction_id: UUID, net_offs: NetOffs):
    """Undo a net off for good: both amounts are owed again."""
    try:
        net_offs.reverse(transaction_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="net off not found!") from None
