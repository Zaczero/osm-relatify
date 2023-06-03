from collections import defaultdict
from dataclasses import dataclass, replace
from enum import Enum
from typing import Self

from models.bounding_box import BoundingBox
from models.element_id import ElementId
from utils import haversine_distance


def _interpolate_coords(latLng1: tuple[float, float], latLng2: tuple[float, float], ratio: float) -> tuple[float, float]:
    lat1, lon1 = latLng1
    lat2, lon2 = latLng2
    lat = lat1 + (lat2 - lat1) * ratio
    lon = lon1 + (lon2 - lon1) * ratio
    return lat, lon


def _calculate_length_and_midpoint(latLngs: list[tuple[float, float]]) -> tuple[float, tuple[float, float]]:
    segment_distances = tuple(
        haversine_distance(latLng1, latLng2)
        for latLng1, latLng2 in zip(latLngs, latLngs[1:]))

    total_distance = sum(segment_distances)
    half_distance = total_distance / 2
    accumulated_distance = 0.0

    for latLng1, latLng2, segment_distance in zip(latLngs, latLngs[1:], segment_distances):
        accumulated_distance += segment_distance

        if accumulated_distance >= half_distance:
            segment_ratio = 1 - (accumulated_distance - half_distance) / segment_distance
            midpoint = _interpolate_coords(latLng1, latLng2, segment_ratio)
            break

    return total_distance, midpoint


@dataclass(kw_only=True, slots=True)
class FetchRelationElement:  # more like FetchRelationWay
    id: ElementId
    member: bool
    oneway: bool
    roundabout: bool
    nodes: list[int]
    latLngs: list[tuple[float, float]]
    connectedTo: list[ElementId]

    # automatically calculated
    length: float = None
    midpoint: tuple[float, float] = None

    def __post_init__(self):
        if self.length is None or self.midpoint is None:
            self.length, self.midpoint = _calculate_length_and_midpoint(self.latLngs)


class PublicTransport(Enum):
    PLATFORM = 'platform'
    STOP_POSITION = 'stop_position'


@dataclass(frozen=True, kw_only=True, slots=True)
class FetchRelationBusStop:
    id: ElementId
    type: str
    member: bool | None
    latLng: tuple[float, float]
    name: str
    highway: str | None
    public_transport: PublicTransport

    @property
    def typed_id(self) -> tuple[str, ElementId]:
        return self.type, self.id

    @classmethod
    def from_data(cls, data: dict) -> Self:
        return cls(
            id=ElementId(data['id']),
            type=data['type'],
            member=None,
            latLng=(data['lat'], data['lon']),
            name=data['tags'].get('name', ''),
            highway=data['tags'].get('highway', None),
            public_transport=PublicTransport(data['tags']['public_transport']))


@dataclass(frozen=True, kw_only=True, slots=True)
class FetchRelationBusStopCollection:
    platform: FetchRelationBusStop | None
    stop: FetchRelationBusStop | None

    @property
    def best(self) -> FetchRelationBusStop:
        return self.platform or self.stop


@dataclass(frozen=True, kw_only=True, slots=True)
class FetchRelation:
    nameOrRef: str
    bounds: BoundingBox
    cells: frozenset[tuple[int, int]]
    tags: dict[str, str]
    startWay: FetchRelationElement
    stopWay: FetchRelationElement
    ways: dict[ElementId, FetchRelationElement]
    busStops: list[FetchRelationBusStopCollection]


def find_start_stop_ways(ways: dict[ElementId, FetchRelationElement], id_map: dict[int, list[ElementId]], relation: dict) -> tuple[FetchRelationElement, FetchRelationElement]:
    member_ids = [
        way['ref'] for way in relation['members']
        if way['type'] == 'way' and way['role'] in {
            '',
            'forward',
            'backward',
            'route'
        }]

    assert member_ids, 'Relation has no way members'

    def get_endpoint_id(way_id: int) -> ElementId | None:
        all_way_ids = id_map[way_id]

        if not all_way_ids:
            return None

        if len(all_way_ids) == 1:
            return all_way_ids[0]

        for endpoint_way_id in [all_way_ids[0], all_way_ids[-1]]:
            endpoint_way = ways[endpoint_way_id]

            if not any(ways[connected_way_id].member
                       for connected_way_id in endpoint_way.connectedTo):
                return endpoint_way_id

        return all_way_ids[len(all_way_ids) // 2]

    start_way_id = get_endpoint_id(member_ids[0])
    stop_way_id = get_endpoint_id(member_ids[-1])

    if start_way_id is None and stop_way_id is not None:
        start_way_id = stop_way_id
    elif start_way_id is not None and stop_way_id is None:
        stop_way_id = start_way_id
    elif start_way_id is None and stop_way_id is None:
        start_way_id = stop_way_id = next(iter(ways))

    return ways[start_way_id], ways[stop_way_id]


def assign_none_members(bus_stop_collections: list[FetchRelationBusStopCollection], relation: dict) -> list[FetchRelationBusStopCollection]:
    collection_stop_use_counter = defaultdict(int)

    for collection in bus_stop_collections:
        if collection.stop is not None:
            collection_stop_use_counter[collection.stop.typed_id] += 1

    member_ids_set = {(m['type'], ElementId(m['ref'])) for m in relation['members']}
    result = []

    for collection in bus_stop_collections:
        member = False

        if collection.platform is not None and collection.platform.member is None:
            platform_key = collection.platform.typed_id
            member = platform_key in member_ids_set

        if not member and collection.stop is not None and collection.stop.member is None:
            stop_key = collection.stop.typed_id

            # collections may share the same stop
            # it's safe to use stop as a member indicator
            # only if it's used by a single collection
            if collection_stop_use_counter[stop_key] == 1:
                member = stop_key in member_ids_set

        collection = replace(collection,
                             platform=replace(collection.platform, member=member) if collection.platform else None,
                             stop=replace(collection.stop, member=member) if collection.stop else None)

        result.append(collection)

    return result
