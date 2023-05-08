from collections import defaultdict
from itertools import chain
from math import radians
from typing import Iterable, NamedTuple

import xmltodict
from asyncache import cached
from cachetools import TTLCache
from sklearn.neighbors import BallTree

from config import OVERPASS_API_INTERPRETER
from models.bounding_box import BoundingBox
from models.element_id import ElementId
from models.fetch_relation import (FetchRelationBusStop,
                                   FetchRelationBusStopCollection,
                                   FetchRelationElement, PublicTransport)
from utils import get_http_client, radians_tuple

# TODO: right hand side detection by querying roundabouts, and first/last bus stop


class QueryParentsResult(NamedTuple):
    id_relations_map: dict[int, list[dict]]
    ways_map: dict[int, dict]


def split_by_count(elements: Iterable[dict]) -> list[list[dict]]:
    result = []
    current_split = []

    for e in elements:
        if e['type'] == 'count':
            result.append(current_split)
            current_split = []
        else:
            current_split.append(e)

    assert not current_split, 'Last element must be count type'
    return result


def build_bb_query(relation_id: int, timeout: int) -> str:
    return \
        f'[out:json][timeout:{timeout}];' \
        f'relation({relation_id});' \
        f'out body bb qt;'


def build_bus_query(bb: BoundingBox, timeout: int) -> str:
    return \
        f'[out:json][timeout:{timeout}][bbox:{bb.minlat},{bb.minlon},{bb.maxlat},{bb.maxlon}];' \
        f'way[highway][!footway];' \
        f'out body qt;' \
        f'out count;' \
        f'>;' \
        f'out skel qt;' \
        f'out count;' \
        f'(' \
        f'node[highway=bus_stop][public_transport=platform];' \
        f'nwr[highway=platform][public_transport=platform];' \
        f'node[public_transport=stop_position];' \
        f');' \
        f'out tags center qt;' \
        f'out count;' \
        f'rel[public_transport=stop_area]->.r;' \
        f'.r out body qt;' \
        f'.r out count;' \
        f'(' \
        f'node(r.r:platform);' \
        f'way(r.r:platform);' \
        f'rel(r.r:platform);' \
        f');' \
        f'out tags center qt;' \
        f'out count;' \
        f'(' \
        f'node(r.r:stop);' \
        f');' \
        f'out tags center qt;' \
        f'out count;'


def build_parents_query(way_ids: Iterable[int], timeout: int) -> str:
    def _parents(way_id: int) -> str:
        return \
            f'way(id:{way_id});' \
            f'(rel(bw);.r;)->.r;'

    return \
        f'[out:xml][timeout:{timeout}];' \
        f'._->.r;' + \
        ''.join(_parents(way_id) for way_id in way_ids) + \
        f'.r out meta qt;' \
        f'way(r.r);' \
        f'out skel qt;'


def is_road(tags: dict[str, str]) -> bool:
    highway_valid = tags['highway'] in {
        'residential',
        'service',
        'unclassified',
        'tertiary',
        'tertiary_link',
        'secondary',
        'secondary_link',
        'primary',
        'primary_link',
        'living_street',
        'trunk',
        'trunk_link',
        'motorway',
        'motorway_link',
        'motorway_junction',
        'road',
        'busway',
        'bus_guideway',
    }

    service_valid = tags.get('service', 'no') not in {
        'driveway',
        'driveway2',
        'parking_aisle',
        'emergency_access',
    }

    access_valid = True

    if 'bus' in tags:
        access_valid = tags['bus'] not in {
            'no'
        }
    elif 'psv' in tags:
        access_valid = tags['psv'] not in {
            'no'
        }
    elif 'access' in tags:
        access_valid = tags['access'] not in {
            'private',
            'customers',
            'no'
        }

    noarea_valid = \
        tags.get('area', 'no') in {
            'no'
        }

    return all((
        highway_valid,
        service_valid,
        access_valid,
        noarea_valid))


def is_oneway(tags: dict[str, str]) -> bool:
    # TODO: it would be nice to support oneway=-1

    roundabout_valid = False

    if 'junction' in tags:
        roundabout_valid = tags['junction'] in {
            'roundabout'
        }

    oneway_valid = roundabout_valid

    if 'oneway:bus' in tags:
        oneway_valid = tags['oneway:bus'] in {
            'yes'
        }
    elif 'oneway:psv' in tags:
        oneway_valid = tags['oneway:psv'] in {
            'yes'
        }
    elif 'oneway' in tags:
        oneway_valid = tags['oneway'] in {
            'yes'
        }

    return oneway_valid


def is_roundabout(tags: dict[str, str]) -> bool:
    return tags.get('junction', 'no') in {
        'roundabout'
    }


def is_rail_related(tags: dict[str, str]) -> bool:
    rail_valid = 'railway' in tags

    train_valid = tags.get('train', 'no') in {
        'yes'
    }

    subway_valid = tags.get('subway', 'no') in {
        'yes'
    }

    tram_valid = tags.get('tram', 'no') in {
        'yes'
    }

    return any((
        rail_valid,
        train_valid,
        subway_valid,
        tram_valid))


def _merge_relation_tags(element: dict, relation: dict, extra: dict) -> None:
    element['tags'] = relation.get('tags', {}) | element.get('tags', {}) | extra


def merge_relations_tags(relations: Iterable[dict], elements: Iterable[dict], role: str, public_transport: str) -> None:
    element_map = {(e['type'], e['id']): e for e in elements}

    for relation in sorted(relations, key=lambda r: r['id']):
        for member in (m for m in relation['members'] if m['role'] == role):

            platform = element_map.get((member['type'], member['ref']), None)

            if platform is None:
                print(f'🚧 Warning: Platform {member["type"]}/{member["ref"]} not found in map')
                continue

            _merge_relation_tags(platform, relation, {'public_transport': public_transport})


def _create_node_counts(ways: list[dict]) -> dict[int, int]:
    node_counts = defaultdict(int)

    for way in ways:
        for node in way['nodes']:
            node_counts[node] += 1

    return node_counts


def _split_way_on_intersection(way: dict, node_counts: dict[int, int]) -> list[list[int]]:
    segments: list[list[int]] = []
    current_segment: list[int] = []

    for node in way['nodes']:
        current_segment.append(node)

        if node_counts[node] > 1 and len(current_segment) > 1:
            segments.append(current_segment)
            current_segment = [node]

    if len(current_segment) > 1:
        segments.append(current_segment)

    return segments


def organize_ways(ways: list[dict]) -> tuple[list[dict], dict[ElementId, set[ElementId]], dict[int, list[ElementId]]]:
    node_counts = _create_node_counts(ways)
    node_to_way_map = defaultdict(set)

    split_ways: list[dict] = []
    connected_ways_map: dict[ElementId, set[ElementId]] = defaultdict(set)
    id_map = defaultdict(list)

    for way in ways:
        split_segments = _split_way_on_intersection(way, node_counts)

        for extraNum, segment in enumerate(split_segments, 1):
            extraNum = extraNum if len(split_segments) > 1 else None
            maxNum = len(split_segments) if extraNum is not None else None

            split_way = way | {
                'id': ElementId(way['id'], extraNum=extraNum, maxNum=maxNum),
                'nodes': segment
            }

            split_ways.append(split_way)
            id_map[way['id']].append(split_way['id'])

            for node in segment:
                if node_counts[node] > 1:
                    for other_way_id in node_to_way_map[node]:
                        connected_ways_map[split_way['id']].add(other_way_id)
                        connected_ways_map[other_way_id].add(split_way['id'])
                    node_to_way_map[node].add(split_way['id'])

    return split_ways, connected_ways_map, id_map


def deduplicate_bus_stops_by_id(bus_stops: Iterable[FetchRelationBusStop]) -> Iterable[FetchRelationBusStop]:
    id_set = set()

    for bus_stop in bus_stops:
        if bus_stop.id not in id_set:
            id_set.add(bus_stop.id)
            yield bus_stop


def create_bus_stop_collections(bus_stops: list[FetchRelationBusStop]) -> list[FetchRelationBusStopCollection]:
    # 1. group by area
    # 2. group by name in area
    # 3. discard unnamed if in area with named
    # 4. for each named group, pick best platform and best stop

    search_meters = 50
    search_latLng = search_meters / 111_111
    search_latLng_rad = radians(search_latLng)

    bus_stops_coordinates = tuple(radians_tuple(bus_stop.latLng) for bus_stop in bus_stops)
    bus_stops_tree = BallTree(bus_stops_coordinates, metric='haversine')

    areas: dict[int, int] = {}

    query_indices, _ = bus_stops_tree.query_radius(
        bus_stops_coordinates,
        r=search_latLng_rad,
        return_distance=True,
        sort_results=True)

    # group by area
    for i, indices in enumerate(query_indices):
        for j in indices[1:]:
            if (j_in := areas.get(j)) is not None:
                areas[i] = j_in
                break
        else:
            areas[i] = i

    area_groups: dict[int, list[FetchRelationBusStop]] = defaultdict(list)

    for member_index, area_index in areas.items():
        area_groups[area_index].append(bus_stops[member_index])

    collections: list[FetchRelationBusStopCollection] = []

    for area_group in area_groups.values():
        # group by name in area
        name_groups: dict[str, list[FetchRelationBusStop]] = defaultdict(list)
        for bus_stop in area_group:
            name_groups[bus_stop.name].append(bus_stop)

        # discard unnamed if in area with named
        if len(name_groups) > 1:
            name_groups.pop('', None)

        # expand non-number suffixed groups to number suffixed groups if needed
        prefix_map = defaultdict(list)

        for name_group_key, name_group in name_groups.items():
            parts = name_group_key.rsplit(' ', 1)

            if len(parts) == 2 and parts[1].isdecimal():
                prefix_map[parts[0].strip()].append(name_group_key)

        for prefix, name_group_keys in prefix_map.items():
            if (prefix_name_group := name_groups.get(prefix)) is None:
                continue

            success = False

            for name_group_key in name_group_keys:
                name_group = name_groups[name_group_key]

                for prefix_bus_stop in prefix_name_group:
                    if not any(
                            bus_stop.public_transport == prefix_bus_stop.public_transport
                            for bus_stop in name_group):
                        name_group.append(prefix_bus_stop)
                        success = True

            if success:
                name_groups.pop(prefix)

        # for each named group, pick best platform and best stop
        for name_group_key, name_group in name_groups.items():
            platforms: list[FetchRelationBusStop] = []
            stops: list[FetchRelationBusStop] = []

            for bus_stop in name_group:
                if bus_stop.public_transport == PublicTransport.PLATFORM:
                    platforms.append(bus_stop)
                elif bus_stop.public_transport == PublicTransport.STOP_POSITION:
                    stops.append(bus_stop)
                else:
                    raise NotImplementedError(f'Unknown public transport type: {bus_stop.public_transport}')

            platforms.sort(key=lambda p: p.id)
            stops.sort(key=lambda s: s.id)

            def pick_best(elements: list[FetchRelationBusStop], others: list[FetchRelationBusStop]) -> list[FetchRelationBusStop]:
                if len(elements) >= 2:
                    elements_bus_stop = tuple(e for e in elements if e.highway == 'bus_stop')
                    elements_else = tuple(e for e in elements if e.highway != 'bus_stop')

                    if len(elements_bus_stop) >= 2:
                        if len(others) >= 2:
                            print(f'🚧 Warning: Unexpected number of elements for {name_group_key}: '
                                  f'{len(elements_bus_stop)=}, {len(elements_else)=}, {len(others)=}')

                    elif len(elements_bus_stop) == 0:
                        print(f'🚧 Warning: Unexpected number of elements for {name_group_key}: '
                              f'{len(elements_bus_stop)=}, {len(elements_else)=}, {len(others)=}')

                    return elements_bus_stop if elements_bus_stop else (elements_else[0],)
                elif len(elements) == 1:
                    return (elements[0],)
                else:
                    return (None,)

            best_platforms = pick_best(platforms, stops)
            best_stops = pick_best(stops, platforms)

            if len(best_platforms) <= 1 or len(best_stops) <= 1:
                for best_platform in best_platforms:
                    for best_stop in best_stops:
                        collections.append(FetchRelationBusStopCollection(
                            platform=best_platform,
                            stop=best_stop))

            else:
                for best_platform in best_platforms:
                    collections.append(FetchRelationBusStopCollection(
                        platform=best_platform,
                        stop=None))

                for best_stop in best_stops:
                    collections.append(FetchRelationBusStopCollection(
                        platform=None,
                        stop=best_stop))

    return collections


class Overpass:
    def __init__(self):
        self.http = get_http_client(OVERPASS_API_INTERPRETER)

    # TODO: check data freshness

    @cached(TTLCache(maxsize=128, ttl=60))
    async def query_relation(self, relation_id: int) -> tuple[BoundingBox, dict[ElementId, FetchRelationElement], dict[int, list[ElementId]], list[FetchRelationBusStopCollection]]:
        timeout = 60
        query = build_bb_query(relation_id, timeout)
        r = await self.http.post('', data={'data': query}, timeout=timeout * 2)
        r.raise_for_status()

        relation = r.json()['elements'][0]

        relation_way_members = set(
            m['ref']
            for m in relation['members']
            if m['type'] == 'way'
        )

        query_bounds = BoundingBox(
            minlat=relation['bounds']['minlat'],
            minlon=relation['bounds']['minlon'],
            maxlat=relation['bounds']['maxlat'],
            maxlon=relation['bounds']['maxlon'],
        ).extend(meters=600)

        timeout = 180
        query = build_bus_query(query_bounds, timeout)
        r = await self.http.post('', data={'data': query}, timeout=timeout * 2)
        r.raise_for_status()

        elements: list[dict] = r.json()['elements']
        elements_split = split_by_count(elements)

        maybe_road_elements = elements_split[0]
        node_elements = elements_split[1]

        bus_elements = elements_split[2]

        stop_area_relations = elements_split[3]
        stop_area_platform_elements = elements_split[4]
        stop_area_stop_position_elements = elements_split[5]

        merge_relations_tags(stop_area_relations, stop_area_platform_elements,
                             role='platform', public_transport='platform')
        merge_relations_tags(stop_area_relations, stop_area_stop_position_elements,
                             role='stop', public_transport='stop_position')

        road_elements = [
            e for e in maybe_road_elements
            if is_road(e['tags'])]

        nodes_map = {
            e['id']: e
            for e in node_elements}

        for e in road_elements:
            e['_member'] = e['id'] in relation_way_members
            e['_oneway'] = is_oneway(e['tags'])
            e['_roundabout'] = is_roundabout(e['tags'])

        road_elements, connected_ways_map, id_map = organize_ways(road_elements)

        ways = {
            e['id']: FetchRelationElement(
                id=e['id'],
                member=e['_member'],
                oneway=e['_oneway'],
                roundabout=e['_roundabout'],
                nodes=e['nodes'],
                latLngs=[
                    (nodes_map[n_id]['lat'], nodes_map[n_id]['lon'])
                    for n_id in e['nodes']
                ],
                connectedTo=list(connected_ways_map[e['id']]),
            )
            for e in road_elements
        }

        bus_elements_ex = [
            e for e in chain(stop_area_platform_elements, stop_area_stop_position_elements, bus_elements)
            if not is_rail_related(e['tags'])]

        # extract center
        for e in bus_elements_ex:
            if 'center' in e:
                e['lat'] = e['center']['lat']
                e['lon'] = e['center']['lon']

        bus_stops = (FetchRelationBusStop.from_data(e) for e in bus_elements_ex)
        bus_stops = tuple(deduplicate_bus_stops_by_id(bus_stops))
        bus_stop_collections = create_bus_stop_collections(bus_stops)

        return query_bounds, ways, id_map, bus_stop_collections

    @cached(TTLCache(maxsize=512, ttl=90))
    async def query_parents(self, way_ids_set: frozenset[int]) -> QueryParentsResult:
        timeout = 60
        query = build_parents_query(way_ids_set, timeout)
        r = await self.http.post('', data={'data': query}, timeout=timeout * 2)
        r.raise_for_status()

        data: dict[str, list[dict]] = xmltodict.parse(
            r.text,
            force_list=('relation', 'way', 'member', 'tag', 'nd'))['osm']

        relations = data['relation']
        id_relations_map = defaultdict(list)

        for relation in relations:
            members = relation['member'] = relation.get('member', [])
            tags = relation['tag'] = relation.get('tag', [])

            if len(members) <= 1:
                continue

            for member in members:
                member_id = int(member['@ref'])
                if member['@type'] == 'way' and member_id in way_ids_set:
                    id_relations_map[member_id].append(relation)

        ways = data['way']
        ways_map = {
            int(w['@id']): w
            for w in ways}

        return QueryParentsResult(
            id_relations_map=id_relations_map,
            ways_map=ways_map)
