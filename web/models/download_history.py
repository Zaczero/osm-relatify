from dataclasses import dataclass
from typing import NamedTuple


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
