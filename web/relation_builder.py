import asyncio
from collections import defaultdict
from dataclasses import replace
from itertools import chain, zip_longest
from typing import Generator, Iterable, NamedTuple, Sequence

import xmltodict
from numba import njit
from sklearn.neighbors import BallTree

from config import CHANGESET_ID_PLACEHOLDER, CREATED_BY
from models.element_id import ElementId, split_element_id
from models.fetch_relation import (FetchRelationBusStopCollection,
                                   FetchRelationElement)
from models.final_route import FinalRoute
from models.relation_member import RelationMember
from openstreetmap import OpenStreetMap
from overpass import Overpass, QueryParentsResult
from utils import EARTH_RADIUS, haversine_distance, radians_tuple


class SortedBusEntry(NamedTuple):
    bus_stop_collection: FetchRelationBusStopCollection
    sort_index: int
    neighbor_id: ElementId
    distance_from_neighbor: float
    right_hand_side: bool | None


@njit(fastmath=True)
def is_right_hand_side(latLng1: tuple[float, float], latLng2: tuple[float, float], latLngTest: tuple[float, float]) -> bool | None:
    if latLng1 == latLngTest or latLng2 == latLngTest:
        return None

    v1 = (latLng2[0] - latLng1[0], latLng2[1] - latLng1[1])
    v2 = (latLngTest[0] - latLng2[0], latLngTest[1] - latLng2[1])

    cross_product_z = v1[0] * v2[1] - v1[1] * v2[0]
    return cross_product_z > 0


@njit(fastmath=True)
def interpolate_latLng(latLng1_rad: tuple[float, float], latLng2_rad: tuple[float, float], threshold: float) -> list[tuple[float, float]]:
    distance = haversine_distance(latLng1_rad, latLng2_rad, unit_radians=True)
    result_size = int(distance / threshold) + 1
    result = [latLng1_rad]

    if result_size > 1:
        delta_lat_rad = (latLng2_rad[0] - latLng1_rad[0]) / result_size
        delta_lng_rad = (latLng2_rad[1] - latLng1_rad[1]) / result_size

        for i in range(1, result_size):
            result.append((latLng1_rad[0] + delta_lat_rad * i, latLng1_rad[1] + delta_lng_rad * i))

    return result


def sort_bus_on_path(bus_stop_collections: list[FetchRelationBusStopCollection], ways: Iterable[FetchRelationElement]) -> list[SortedBusEntry]:
    interpolate_threshold = 60  # meters
    latLng_rad_idx_way_map: dict[tuple, tuple[int, FetchRelationElement]] = {}
    tree_coordinates_rad = []

    for way in ways:
        way_latLngs_rad = tuple(radians_tuple(latLng) for latLng in way.latLngs)
        for idx, (current_latLng_rad, next_latLng_rad) in enumerate(zip_longest(way_latLngs_rad, way_latLngs_rad[1:], fillvalue=way_latLngs_rad[-1])):
            for latLng_rad in interpolate_latLng(current_latLng_rad, next_latLng_rad, interpolate_threshold):
                latLng_rad_idx_way_map[latLng_rad] = (idx, way)
                tree_coordinates_rad.append(latLng_rad)

    tree = BallTree(tree_coordinates_rad, metric='haversine')

    collections_latLng_rad = tuple(radians_tuple(collection.best.latLng) for collection in bus_stop_collections)
    distances, idxs = tree.query(collections_latLng_rad, k=1, return_distance=True, sort_results=False)

    result = []

    for collection, collection_latLng_rad, distance, idx in zip(bus_stop_collections, collections_latLng_rad, distances, idxs):
        distance = distance[0] * EARTH_RADIUS
        idx = idx[0]

        neighbor_latLng_rad = tree_coordinates_rad[idx]
        neighbor_latLngs_idx, neighbor_way = latLng_rad_idx_way_map[neighbor_latLng_rad]

        if neighbor_latLngs_idx > 0:
            right_hand_side = is_right_hand_side(
                radians_tuple(neighbor_way.latLngs[neighbor_latLngs_idx - 1]),
                neighbor_latLng_rad,
                collection_latLng_rad)
        elif neighbor_latLngs_idx + 1 < len(neighbor_way.latLngs):
            right_hand_side = is_right_hand_side(
                neighbor_latLng_rad,
                radians_tuple(neighbor_way.latLngs[neighbor_latLngs_idx + 1]),
                collection_latLng_rad)
        else:
            right_hand_side = None

        result.append(SortedBusEntry(
            bus_stop_collection=collection,
            sort_index=idx,
            neighbor_id=neighbor_way.id,
            distance_from_neighbor=distance,
            right_hand_side=right_hand_side))

    assert not any(e.sort_index == -1 for e in result)
    return sorted(result, key=lambda x: x.sort_index)  # TODO: sort stop, platform on the same sort_index


def _simplify_way_ids(way_ids: list[ElementId]) -> list[ElementId]:
    way_ids_parts = tuple(split_element_id(way_id) for way_id in way_ids)
    simplify_blacklist: set[int] = set()

    # pass 1, fill blacklist
    i = 0
    while i < len(way_ids_parts):
        way_id, way_id_parts = way_ids[i], way_ids_parts[i]

        if way_id_parts.extraNum == 1 or (way_id_parts.extraNum is not None and way_id_parts.extraNum == way_id_parts.maxNum):
            last_i = i + way_id_parts.maxNum - 1

            if last_i < len(way_ids):
                if all(other_way_id_parts.id == way_id_parts.id for other_way_id_parts in way_ids_parts[i + 1:last_i + 1]):
                    # simplify
                    i += way_id_parts.maxNum
                    continue
                else:
                    simplify_blacklist.add(way_id_parts.id)
            else:
                simplify_blacklist.add(way_id_parts.id)

        i += 1

    result = []

    # pass 2, generate results
    i = 0
    while i < len(way_ids_parts):
        way_id, way_id_parts = way_ids[i], way_ids_parts[i]

        if way_id_parts.id not in simplify_blacklist:
            if way_id_parts.extraNum == 1 or (way_id_parts.extraNum is not None and way_id_parts.extraNum == way_id_parts.maxNum):
                last_i = i + way_id_parts.maxNum - 1

                if last_i < len(way_ids):
                    if all(other_way_id_parts.id == way_id_parts.id for other_way_id_parts in way_ids_parts[i + 1:last_i + 1]):
                        # simplify
                        result.append(ElementId(way_id_parts.id))
                        i += way_id_parts.maxNum
                        continue

        result.append(way_id)
        i += 1

    return result


def get_relation_members(relation: dict) -> list[RelationMember]:
    return [RelationMember(
        id=ElementId(m['ref']),
        type=m['type'],
        role=m['role'])
        for m in relation['members']]


def sort_and_upgrade_members(route: FinalRoute, relation_members: list[RelationMember]) -> FinalRoute:
    id_relation_member_map = {
        member.id: member
        for member in relation_members}

    members = []

    for i, collection in enumerate(route.busStops):
        is_first = i == 0
        is_last = i == len(route.busStops) - 1
        suffix = '_entry_only' if is_first else ('_exit_only' if is_last else '')

        if collection.stop is not None:
            role = 'stop' + suffix

            if (member := id_relation_member_map.get(collection.stop.id, None)) is not None:
                if member.role.startswith(role):
                    role = member.role

            members.append(RelationMember(id=collection.stop.id, type=collection.stop.type, role=role))

        if collection.platform is not None:
            role = 'platform' + suffix

            if (member := id_relation_member_map.get(collection.platform.id, None)) is not None:
                if member.role.startswith(role):
                    role = member.role

            members.append(RelationMember(id=collection.platform.id, type=collection.platform.type, role=role))

    way_ids = [route_way.way.id for route_way in route.ways]
    way_ids = _simplify_way_ids(way_ids)

    for way_id in way_ids:
        role = ''

        if (member := id_relation_member_map.get(way_id, None)) is not None:
            if member.role not in {'route', 'forward', 'backward'}:
                role = member.role

        members.append(RelationMember(id=way_id, type='way', role=role))

    return replace(route, members=tuple(members))


def _initialize_osm_change_structure() -> dict:
    return {
        'osmChange': {
            '@version': 0.6,
            '@generator': CREATED_BY,
            'create': {
                'way': [],
            },
            'modify': {
                'way': [],
                'relation': []
            }
        }
    }


def _set_changeset_placeholder(data: dict, include_changeset_id: bool) -> None:
    if include_changeset_id:
        data['@changeset'] = CHANGESET_ID_PLACEHOLDER
    else:
        data.pop('@changeset', None)


def _update_relations_after_split(ignore_relation_id: int, split_ways: frozenset[int], parents: QueryParentsResult, native_id_element_ids_map: dict[int, dict[int, ElementId]], id_way_map: dict[ElementId, FetchRelationElement], element_id_unique_map: dict[ElementId, int], unique_native_id_map: dict[int, int]) -> list[dict]:
    result: dict[int, dict] = {}

    # iterate over the split ways
    for way_id in split_ways:
        way = id_way_map[native_id_element_ids_map[way_id][1]]

        # iterate over each related relation
        for relation in parents.id_relations_map[way_id]:
            relation_id = int(relation['@id'])

            if relation_id == ignore_relation_id:
                continue

            result[relation_id] = relation

            first_way_index = next(
                i for i, member in enumerate(relation['member'])
                if member['@type'] == 'way' and not any(member['@role'].startswith(s) for s in ('stop', 'platform')))

            way_index = next(
                i for i, member in enumerate(relation['member'])
                if int(member['@ref']) == way_id)

            way_index_relative_to_first = way_index - first_way_index

            way_role = relation['member'][way_index]['@role']

            split_ways_in_order = list(native_id_element_ids_map[way_id].items())
            split_ways_in_order.sort(key=lambda x: x[0])

            # determine the order of the split ways
            if way_index_relative_to_first > 0 and (before_entry := relation['member'][way_index - 1]) and before_entry['@type'] == 'way':
                before_way_id = int(before_entry['@ref'])
                before_way_id = unique_native_id_map.get(before_way_id, before_way_id)
                before_way = parents.ways_map[before_way_id]
                before_way['nd'] = before_way.get('nd', [])

                if before_way['nd']:
                    for check in (0, -1):
                        if int(before_way['nd'][check]['@ref']) == way.nodes[-1]:
                            split_ways_in_order.reverse()
                            break

            elif way_index_relative_to_first == 0 and way_index + 1 < len(relation['member']) and (after_entry := relation['member'][way_index + 1]) and after_entry['@type'] == 'way':
                after_way_id = int(after_entry['@ref'])
                after_way_id = unique_native_id_map.get(after_way_id, after_way_id)
                after_way = parents.ways_map[after_way_id]
                after_way['nd'] = after_way.get('nd', [])

                if after_way['nd']:
                    for check in (0, -1):
                        if int(after_way['nd'][check]['@ref']) == way.nodes[0]:
                            split_ways_in_order.reverse()
                            break

            # remove the original way from the relation member list
            relation['member'].pop(way_index)

            # replace the original way in the relation member list with the split ways
            for i, (_, element_id) in enumerate(split_ways_in_order):
                relation['member'].insert(way_index + i, {
                    '@type': 'way',
                    '@ref': element_id_unique_map.get(element_id, element_id),
                    '@role': way_role,
                })

                # TODO: support restriction-type relations

    return result.values()


async def build_osm_change(relation_id: int, route: FinalRoute, include_changeset_id: bool, overpass: Overpass, osm: OpenStreetMap) -> str:
    split_ways: set[int] = set()
    native_id_element_ids_map: dict[int, dict[int, ElementId]] = defaultdict(dict)
    element_id_unique_map: dict[ElementId, int] = {}
    unique_native_id_map: dict[int, int] = {}
    next_unique_id: int = -1

    # iterate over route members and check if they are split
    for obj in chain(route.members, (way for way in route.extraWaysToUpdate)):
        element_id = obj.id
        element_id_parts = split_element_id(element_id)

        if element_id_parts.extraNum is not None:
            split_ways.add(element_id_parts.id)
            native_id_element_ids_map[element_id_parts.id][element_id_parts.extraNum] = element_id

            if element_id_parts.extraNum == 1:
                element_id_unique_map[element_id] = element_id_parts.id
            else:
                element_id_unique_map[element_id] = next_unique_id
                unique_native_id_map[next_unique_id] = element_id_parts.id
                next_unique_id -= 1

    for group in native_id_element_ids_map.values():
        assert len(group) == split_element_id(group[1]).maxNum, \
            f'Split ways are not complete: {", ".join(f"{k}={v}" for k, v in group.items())}'

    split_ways = frozenset(split_ways)

    parents_task = asyncio.create_task(overpass.query_parents(split_ways)) if split_ways else None
    ways_task = asyncio.create_task(osm.get_ways(map(str, split_ways), json=False)) if split_ways else None
    relation_task = asyncio.create_task(osm.get_relation(relation_id, json=False))

    result = _initialize_osm_change_structure()

    if ways_task:
        ways = await ways_task

        id_way_map = \
            {route_way.way.id: route_way.way for route_way in route.ways} | \
            {way.id: way for way in route.extraWaysToUpdate}

        # process fetched ways (split ways)
        for way_data in ways:
            way_id = int(way_data['@id'])

            # strip unnecessary data
            way_data.pop('@timestamp', None)
            way_data.pop('@user', None)
            way_data.pop('@uid', None)

            # perform splits
            for extraNum, element_id in native_id_element_ids_map[way_id].items():
                element_way = id_way_map[element_id]

                new_data = way_data.copy()

                if extraNum == 1:
                    action = 'modify'
                else:
                    action = 'create'
                    new_data['@id'] = element_id_unique_map[element_id]
                    new_data.pop('@version', None)

                _set_changeset_placeholder(new_data, include_changeset_id)

                new_data['nd'] = [
                    {'@ref': node_id}
                    for node_id in element_way.nodes]

                result['osmChange'][action]['way'].append(new_data)

        parents: QueryParentsResult = await parents_task

        # update relations
        parent_relations = _update_relations_after_split(
            ignore_relation_id=relation_id,
            split_ways=split_ways,
            parents=parents,
            native_id_element_ids_map=native_id_element_ids_map,
            id_way_map=id_way_map,
            element_id_unique_map=element_id_unique_map,
            unique_native_id_map=unique_native_id_map)

        for parent_relation in parent_relations:
            # strip unnecessary data
            parent_relation.pop('@timestamp', None)
            parent_relation.pop('@user', None)
            parent_relation.pop('@uid', None)

            # update relation data
            _set_changeset_placeholder(parent_relation, include_changeset_id)

            result['osmChange']['modify']['relation'].append(parent_relation)

    relation_data = await relation_task

    # strip unnecessary data
    relation_data.pop('@timestamp', None)
    relation_data.pop('@user', None)
    relation_data.pop('@uid', None)

    # update relation data
    _set_changeset_placeholder(relation_data, include_changeset_id)

    relation_data['member'] = [
        {'@type': member.type, '@ref': element_id_unique_map.get(member.id, member.id), '@role': member.role}
        for member in route.members]

    result['osmChange']['modify']['relation'].append(relation_data)

    return xmltodict.unparse(result, pretty=not include_changeset_id)
