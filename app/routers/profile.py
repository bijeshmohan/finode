from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Profiles
from ..schemas.profile import ProfileRead, ProfileUpdate


router = APIRouter(
    prefix="/profile",
    tags=["profile"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/", response_model=ProfileRead)
def get_profile(profiles: Profiles):
    return profiles.read()


@router.patch("/", response_model=ProfileRead)
def update_profile(data: ProfileUpdate, profiles: Profiles):
    try:
        return profiles.update(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
