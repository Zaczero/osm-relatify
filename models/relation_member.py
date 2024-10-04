from dataclasses import dataclass

from models.element_id import ElementId


@dataclass(frozen=True, kw_only=True, slots=True)
class RelationMember:
    id: ElementId
    type: str
    role: str
