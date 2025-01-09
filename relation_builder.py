import asyncio
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import replace
from itertools import chain, cycle, islice, zip_longest
from typing import NamedTuple

import xmltodict
from fastapi import HTTPException
from sklearn.neighbors import BallTree
from starlette import status

from config import CHANGESET_ID_PLACEHOLDER, CREATED_BY
from cython_lib.geoutils import haversine_distance, radians_tuple
from models.element_id import ElementId, element_id, split_element_id
from models.fetch_relation import FetchRelationBusStopCollection, FetchRelationElement
from models.final_route import FinalRoute
from models.relation_member import RelationMember
from openstreetmap import OpenStreetMap
from overpass import Overpass, QueryParentsResult


class SortedBusEntry(NamedTuple):
    bus_stop_collection: FetchRelationBusStopCollection
    sort_index: int
    neighbor_id: ElementId
    distance_from_neighbor: float
    right_hand_side: bool | None


def is_right_hand_side(
    lat_lon_start: tuple[float, float],
    lat_lon_end: tuple[float, float],
    lat_lon_test: tuple[float, float],
) -> bool | None:
    if lat_lon_start == lat_lon_test or lat_lon_end == lat_lon_test:
        return None
    v1 = (lat_lon_end[0] - lat_lon_start[0], lat_lon_end[1] - lat_lon_start[1])
    v2 = (lat_lon_test[0] - lat_lon_end[0], lat_lon_test[1] - lat_lon_end[1])
    cross_product_z = v1[0] * v2[1] - v1[1] * v2[0]
    return cross_product_z > 0


def interpolate_latLng(
    lat_lon_start_rad: tuple[float, float],
    lat_lon_stop_rad: tuple[float, float],
    threshold: float,
) -> list[tuple[float, float]]:
    distance = haversine_distance(lat_lon_start_rad, lat_lon_stop_rad, unit_radians=True)
    result_size = int(distance / threshold) + 1
    if result_size == 1:
        return [lat_lon_start_rad]
    delta_lat_rad = (lat_lon_stop_rad[0] - lat_lon_start_rad[0]) / result_size
    delta_lon_rad = (lat_lon_stop_rad[1] - lat_lon_start_rad[1]) / result_size
    return [
        (lat_lon_start_rad[0] + delta_lat_rad * i, lat_lon_start_rad[1] + delta_lon_rad * i)  #
        for i in range(result_size)
    ]


def sort_bus_on_path(
    bus_stop_collections: Sequence[FetchRelationBusStopCollection], ways: Iterable[FetchRelationElement]
) -> list[SortedBusEntry]:
    if not bus_stop_collections:
        return []

    interpolate_threshold = 60  # meters
    latLng_rad_idx_way_map: dict[tuple, tuple[int, FetchRelationElement]] = {}
    tree_coordinates_rad = []

    for way in ways:
        way_latLngs_rad = tuple(radians_tuple(latLng) for latLng in way.latLngs)
        for idx, (current_latLng_rad, next_latLng_rad) in enumerate(
            zip_longest(way_latLngs_rad, way_latLngs_rad[1:], fillvalue=way_latLngs_rad[-1])
        ):
            for latLng_rad in interpolate_latLng(current_latLng_rad, next_latLng_rad, interpolate_threshold):
                latLng_rad_idx_way_map[latLng_rad] = (idx, way)
                tree_coordinates_rad.append(latLng_rad)

    tree = BallTree(tree_coordinates_rad, metric='haversine')

    collections_latLng_rad = tuple(radians_tuple(collection.best.latLng) for collection in bus_stop_collections)
    distances, idxs = tree.query(collections_latLng_rad, k=1, return_distance=True, sort_results=False)

    result: list[SortedBusEntry] = []

    for collection, collection_latLng_rad, distance, idx in zip(
        bus_stop_collections, collections_latLng_rad, distances, idxs, strict=False
    ):
        distance = distance[0] * 6_371_000  # earth radius
        idx = idx[0]

        neighbor_latLng_rad = tree_coordinates_rad[idx]
        neighbor_latLngs_idx, neighbor_way = latLng_rad_idx_way_map[neighbor_latLng_rad]

        if neighbor_latLngs_idx > 0:
            right_hand_side = is_right_hand_side(
                radians_tuple(neighbor_way.latLngs[neighbor_latLngs_idx - 1]),
                neighbor_latLng_rad,
                collection_latLng_rad,
            )
        elif neighbor_latLngs_idx + 1 < len(neighbor_way.latLngs):
            right_hand_side = is_right_hand_side(
                neighbor_latLng_rad,
                radians_tuple(neighbor_way.latLngs[neighbor_latLngs_idx + 1]),
                collection_latLng_rad,
            )
        else:
            right_hand_side = None

        result.append(
            SortedBusEntry(
                bus_stop_collection=collection,
                sort_index=idx,
                neighbor_id=neighbor_way.id,
                distance_from_neighbor=distance,
                right_hand_side=right_hand_side,
            )
        )

    assert not any(e.sort_index == -1 for e in result)
    return sorted(result, key=lambda x: x.sort_index)  # TODO: sort stop, platform on the same sort_index


def _unsplit_way_ids(way_ids: list[ElementId]) -> list[ElementId]:
    way_ids_parts = tuple(map(split_element_id, way_ids))
    simplify_whitelist: set[int] = set()
    simplify_blacklist: list[int] = []

    # pass 1, create blacklist
    i = 0
    while i < len(way_ids_parts):
        way_id_parts = way_ids_parts[i]

        # skip: not-split way
        if way_id_parts.extra_num is None:
            i += 1
            continue
        assert way_id_parts.max_num is not None

        # skip and blacklist: mid-split way
        if 1 < way_id_parts.extra_num < way_id_parts.max_num:
            simplify_blacklist.append(way_id_parts.id)
            i += 1
            continue

        i_end = i + way_id_parts.max_num - 1

        # skip and blacklist: out-of-bounds way
        if i_end >= len(way_ids):
            simplify_blacklist.append(way_id_parts.id)
            i += 1
            continue

        # skip and blacklist: non-linear way
        if not all(
            other_way_id_parts.id == way_id_parts.id  #
            for other_way_id_parts in way_ids_parts[i + 1 : i_end + 1]
        ):
            simplify_blacklist.append(way_id_parts.id)
            i += 1
            continue

        # ok to simplify
        simplify_whitelist.add(way_id_parts.id)
        i += way_id_parts.max_num

    simplify_whitelist.difference_update(simplify_blacklist)
    result: list[ElementId] = []

    # pass 2, generate results
    i = 0
    while i < len(way_ids_parts):
        way_id_parts = way_ids_parts[i]

        if way_id_parts.id not in simplify_whitelist:
            way_id = way_ids[i]
            result.append(way_id)
            i += 1
            continue
        assert way_id_parts.max_num is not None

        # simplify
        result.append(element_id(way_id_parts.id))
        i += way_id_parts.max_num

    return result


def get_relation_members(relation: dict) -> list[RelationMember]:
    return [RelationMember(id=element_id(m['ref']), type=m['type'], role=m['role']) for m in relation['members']]


def sort_and_upgrade_members(route: FinalRoute, relation_members: list[RelationMember]) -> FinalRoute:
    id_relation_member_map = {member.id: member for member in relation_members}

    members: list[RelationMember] = []
    last_stop_member: RelationMember | None = None
    last_platform_member: RelationMember | None = None

    for i, collection in enumerate(route.busStops):
        last_stop_member = None
        last_platform_member = None
        is_first = i == 0
        is_last = i == len(route.busStops) - 1
        suffix = '_entry_only' if is_first else ('_exit_only' if is_last else '')

        if collection.stop is not None:
            role = 'stop' + suffix
            member = id_relation_member_map.get(collection.stop.id)
            if member is not None and member.role.startswith(role):
                role = member.role
            if route.roundtrip and role in {'stop_entry_only', 'stop_exit_only'}:
                role = 'stop'
            last_stop_member = RelationMember(id=collection.stop.id, type=collection.stop.type, role=role)
            members.append(last_stop_member)

        if collection.platform is not None:
            role = 'platform' + suffix
            member = id_relation_member_map.get(collection.platform.id)
            if member is not None and member.role.startswith(role):
                role = member.role
            if route.roundtrip and role in {'platform_entry_only', 'platform_exit_only'}:
                role = 'platform'
            last_platform_member = RelationMember(id=collection.platform.id, type=collection.platform.type, role=role)
            members.append(last_platform_member)

    if route.roundtrip and members:
        # order: stop, platform
        if last_platform_member is not None:
            members.insert(0, last_platform_member)
        if last_stop_member is not None:
            members.insert(0, last_stop_member)

    way_ids = [route_way.way.id for route_way in route.ways]
    way_ids = _unsplit_way_ids(way_ids)

    for way_id in way_ids:
        role = ''

        member = id_relation_member_map.get(way_id)
        if member is not None and member.role not in {'route', 'forward', 'backward'}:
            role = member.role

        members.append(RelationMember(id=way_id, type='way', role=role))

    return replace(route, members=tuple(members))


def _initialize_osm_change_structure() -> dict:
    return {
        'osmChange': {
            '@version': 0.6,
            '@generator': CREATED_BY,
            'create': {'way': []},
            'modify': {'way': [], 'relation': []},
        }
    }


def _set_changeset_placeholder(data: dict, include_changeset_id: bool) -> None:
    if include_changeset_id:
        data['@changeset'] = CHANGESET_ID_PLACEHOLDER
    else:
        data.pop('@changeset', None)


# TODO: support restriction-type relations
def _update_relations_after_split(
    ignore_relation_id: int,
    split_ways: frozenset[int],
    parents: QueryParentsResult,
    native_id_element_ids_map: dict[int, dict[int, ElementId]],
    id_way_map: dict[ElementId, FetchRelationElement],
    element_id_unique_map: dict[ElementId, int],
    unique_native_id_map: dict[int, int],
) -> Collection[dict]:
    result: dict[int, dict] = {}

    # iterate over the split ways
    for way_id in split_ways:
        element_ids = native_id_element_ids_map[way_id]

        # assert unique relations
        assert len(parents.id_relations_map[way_id]) == len({r['@id'] for r in parents.id_relations_map[way_id]})

        # iterate over each related relation
        for relation in parents.id_relations_map[way_id]:
            if relation['@id'] == ignore_relation_id:
                continue

            result[relation['@id']] = relation

            member_index = 0
            while member_index < len(relation['member']):
                member = relation['member'][member_index]

                if not (member['@ref'] == way_id and member['@type'] == 'way'):
                    member_index += 1
                    continue

                way_role = relation['member'][member_index]['@role']

                split_ways_in_order = sorted(element_ids.items(), key=lambda x: x[0])
                first_way_nd = id_way_map[split_ways_in_order[0][1]].nodes[0]
                last_way_nd = id_way_map[split_ways_in_order[-1][1]].nodes[-1]
                is_reversed = False

                if (
                    member_index > 0
                    and (before_entry := relation['member'][member_index - 1])
                    and before_entry['@type'] == 'way'
                ):
                    before_way_id = before_entry['@ref']
                    before_way_id = unique_native_id_map.get(before_way_id, before_way_id)
                    before_way = parents.ways_map.get(before_way_id)
                    if before_way and not before_way.get('nd'):
                        before_way = None
                else:
                    before_way = None

                if (
                    member_index + 1 < len(relation['member'])
                    and (after_entry := relation['member'][member_index + 1])
                    and after_entry['@type'] == 'way'
                ):
                    after_way_id = after_entry['@ref']
                    after_way_id = unique_native_id_map.get(after_way_id, after_way_id)
                    after_way = parents.ways_map.get(after_way_id)
                    if after_way and not after_way.get('nd'):
                        after_way = None
                else:
                    after_way = None

                if first_way_nd != last_way_nd:
                    # reverse is only valid for non-circular ways, e.g. roundabouts

                    if before_way is not None:
                        if any(before_way['nd'][check]['@ref'] == last_way_nd for check in (0, -1)):
                            split_ways_in_order.reverse()
                            first_way_nd, last_way_nd = last_way_nd, first_way_nd
                            is_reversed = True

                    elif after_way is not None:
                        if any(after_way['nd'][check]['@ref'] == first_way_nd for check in (0, -1)):
                            split_ways_in_order.reverse()
                            first_way_nd, last_way_nd = last_way_nd, first_way_nd
                            is_reversed = True

                # remove the original way from the relation member list
                relation['member'].pop(member_index)

                # replace the original way in the relation member list with the split ways
                safe_to_insert = before_way is None
                insert_count = 0

                for _, element_id in islice(cycle(split_ways_in_order), len(split_ways_in_order) * 2):
                    element = id_way_map[element_id]

                    if not is_reversed:
                        first_element_nd, last_element_nd = element.nodes[0], element.nodes[-1]
                    else:
                        first_element_nd, last_element_nd = element.nodes[-1], element.nodes[0]

                    if not safe_to_insert:
                        assert before_way is not None
                        safe_to_insert = any(before_way['nd'][check]['@ref'] == first_element_nd for check in (0, -1))

                    if not safe_to_insert:
                        continue

                    relation['member'].insert(
                        member_index,
                        {
                            '@type': 'way',
                            '@ref': element_id_unique_map.get(element_id, element_id),
                            '@role': way_role,
                        },
                    )

                    member_index += 1
                    insert_count += 1

                    # stop inserting if exhausted the split ways
                    if insert_count == len(split_ways_in_order):
                        break

                    # stop inserting if the next way is the after way
                    if (after_way is not None) and any(
                        after_way['nd'][check]['@ref'] == last_element_nd for check in (0, -1)
                    ):
                        break

                # fallback to dummy insert if none were inserted
                if insert_count == 0:
                    print(f'🚧 Warning: Could not insert split ways into relation {relation["@id"]} (way {way_id})')
                    for _, element_id in split_ways_in_order:
                        relation['member'].insert(
                            member_index,
                            {
                                '@type': 'way',
                                '@ref': element_id_unique_map.get(element_id, element_id),
                                '@role': way_role,
                            },
                        )

                        member_index += 1
                        insert_count += 1

    return result.values()


async def build_osm_change(
    relation_id: int, route: FinalRoute, include_changeset_id: bool, overpass: Overpass, osm: OpenStreetMap
) -> str:
    split_ways_mutable: set[int] = set()
    native_id_element_ids_map: dict[int, dict[int, ElementId]] = defaultdict(dict)
    element_id_unique_map: dict[ElementId, int] = {}
    unique_native_id_map: dict[int, int] = {}
    next_unique_id: int = -1

    # iterate over route members and check if they are split
    for obj in chain(route.members, route.extraWaysToUpdate):
        element_id = obj.id
        element_id_parts = split_element_id(element_id)
        if element_id_parts.extra_num is None:
            continue

        split_ways_mutable.add(element_id_parts.id)
        native_id_element_ids_map[element_id_parts.id][element_id_parts.extra_num] = element_id

        if element_id in element_id_unique_map:
            continue
        if element_id_parts.extra_num == 1:
            element_id_unique_map[element_id] = element_id_parts.id
        else:
            element_id_unique_map[element_id] = next_unique_id
            unique_native_id_map[next_unique_id] = element_id_parts.id
            next_unique_id -= 1

    for group in native_id_element_ids_map.values():
        if (1 not in group) or len(group) != split_element_id(group[1]).max_num:
            raise AssertionError(f'Split ways are not complete: {", ".join(f"{k}={v}" for k, v in group.items())}')

    split_ways = frozenset(split_ways_mutable)
    relation_task = asyncio.create_task(osm.get_relation(relation_id, json=False))

    result = _initialize_osm_change_structure()

    if split_ways:
        parents_task = asyncio.create_task(overpass.query_parents(split_ways))
        ways_task = asyncio.create_task(osm.get_ways(map(str, split_ways), json=False))
        ways = await ways_task

        id_way_map = dict(
            chain(
                ((route_way.way.id, route_way.way) for route_way in route.ways),
                ((way.id, way) for way in route.extraWaysToUpdate),
            )
        )

        # process fetched ways (split ways)
        for way_data in ways:
            way_id = int(way_data['@id'])
            way_data.pop('@timestamp', None)
            way_data.pop('@user', None)
            way_data.pop('@uid', None)
            _set_changeset_placeholder(way_data, include_changeset_id)

            # perform splits
            for extra_num, element_id in native_id_element_ids_map[way_id].items():
                element_way = id_way_map[element_id]

                new_data = way_data.copy()
                new_data['nd'] = [{'@ref': node_id} for node_id in element_way.nodes]

                if extra_num == 1:
                    action = 'modify'

                    # split conflict check
                    way_data_nd = way_data.get('nd')
                    if (
                        way_data_nd
                        and int(way_data_nd[0]['@ref']) == new_data['nd'][0]['@ref']
                        and int(way_data_nd[-1]['@ref']) == new_data['nd'][-1]['@ref']
                    ):
                        raise HTTPException(
                            status.HTTP_409_CONFLICT,
                            f'Conflict: Way {way_id} was modified. Go back and click the relation reload button.',
                        )
                else:
                    action = 'create'
                    new_data['@id'] = element_id_unique_map[element_id]
                    new_data.pop('@version', None)

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
            unique_native_id_map=unique_native_id_map,
        )

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
        for member in route.members
    ]

    result['osmChange']['modify']['relation'].append(relation_data)

    return xmltodict.unparse(result, pretty=not include_changeset_id)
