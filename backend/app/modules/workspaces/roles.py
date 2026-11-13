from enum import StrEnum


class Role(StrEnum):
    viewer = "viewer"
    editor = "editor"
    admin = "admin"
    owner = "owner"

    @property
    def rank(self) -> int:
        return _RANK[self]

    def at_least(self, other: "Role") -> bool:
        return self.rank >= other.rank


_RANK = {Role.viewer: 1, Role.editor: 2, Role.admin: 3, Role.owner: 4}
