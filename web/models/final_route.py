from dataclasses import dataclass, field
from enum import Enum

from models.fetch_relation import FetchRelationBusStopCollection, FetchRelationElement
from models.relation_member import RelationMember


@dataclass(frozen=True, kw_only=True, slots=True)
class FinalRouteWay:
    way: FetchRelationElement
    reversed_latLngs: bool


# tuples fail to decode from json, so we use lists
class WarningSeverity(Enum):
    LOW = ['LOW', 0]
    HIGH = ['HIGH', 1]

    UNCHANGED = ['UNCHANGED', 10]


@dataclass(frozen=True, kw_only=True, slots=True)
class FinalRouteWarning:
    severity: WarningSeverity
    message: str
    extra: tuple = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True, slots=True)
class FinalRoute:
    ways: tuple[FinalRouteWay, ...]
    latLngs: tuple[tuple[float, float], ...]
    busStops: tuple[FetchRelationBusStopCollection, ...]
    tags: dict[str, str]

    # remaining parts of split ways, which are not members of the route
    extraWaysToUpdate: tuple[FetchRelationElement, ...] = None

    members: tuple[RelationMember, ...] = None

    warnings: tuple[FinalRouteWarning, ...] = None

    @property
    def roundtrip(self) -> bool:
        return self.tags.get('roundtrip', 'no') == 'yes'
