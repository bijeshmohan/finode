from ..repositories import ProfileRepository
from ..schemas.profile import ProfileRead, ProfileUpdate


class ProfileService:
    def __init__(self, pr: ProfileRepository):
        self.pr = pr

    @staticmethod
    def _to_read(profile) -> ProfileRead:
        return ProfileRead(
            first_name=profile.first_name,
            last_name=profile.last_name,
            created=profile.created,
            updated=profile.updated,
        )

    def read(self) -> ProfileRead:
        return self._to_read(self.pr.get_or_create())

    def update(self, data: ProfileUpdate) -> ProfileRead:
        return self._to_read(self.pr.update(data))
