import secrets
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Cell:
    x: int
    y: int


@dataclass(frozen=True, kw_only=True, slots=True)
class DownloadHistory:
    session: str
    history: tuple[tuple[Cell, ...], ...]

    def __hash__(self) -> int:
        return hash(self.session)

    @staticmethod
    def make_session() -> str:
        return secrets.token_urlsafe(16)
