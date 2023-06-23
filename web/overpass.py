import secrets
from collections import defaultdict
from dataclasses import replace
from itertools import chain
from math import radians
from typing import Iterable, NamedTuple, Sequence

import httpx
import xmltodict
from asyncache import cached
from cachetools import TTLCache
from sklearn.neighbors import BallTree

from config import (BUS_COLLECTION_SEARCH_AREA,
                    DOWNLOAD_RELATION_GRID_CELL_EXPAND,
                    DOWNLOAD_RELATION_WAY_BB_EXPAND, OVERPASS_API_INTERPRETER)
from models.bounding_box import BoundingBox
from models.bounding_box_collection import BoundingBoxCollection
from models.download_history import Cell, DownloadHistory
from models.element_id import ElementId
from models.fetch_relation import (FetchRelationBusStop,
                                   FetchRelationBusStopCollection,
                                   FetchRelationElement, PublicTransport)
from utils import get_http_client, radians_tuple
from xmltodict_postprocessor import postprocessor

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
        f'rel({relation_id});' \
        f'way(r);' \
        f'out ids bb qt;'


def build_bus_query(cell_bbs: Sequence[BoundingBox], cell_bbs_expanded: Sequence[BoundingBox], timeout: int) -> str:
    return \
        f'[out:json][timeout:{timeout}];' \
        f'(' + \
        ''.join(
            f'way[highway][!footway]({bb});'
            for bb in cell_bbs) + \
        f');' \
        f'out body qt;' \
        f'out count;' \
        f'>;' \
        f'out skel qt;' \
        f'out count;' + \
        f'(' + \
        ''.join(
            f'node[highway=bus_stop][public_transport=platform]({bb});'
            f'nwr[highway=platform][public_transport=platform]({bb});'
            f'node[public_transport=stop_position]({bb});'
            for bb in cell_bbs_expanded) + \
        f');' \
        f'out tags center qt;' \
        f'out count;' \
        f'(' + \
        ''.join(
            f'rel[public_transport=stop_area]({bb});'
            for bb in cell_bbs_expanded) + \
        f')->.r;' \
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
            f'way({way_id});' \
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
        'alley',
        'emergency_access',
    }

    access_designated = False
    access_valid = True

    if 'bus' in tags:
        access_designated = access_valid = tags['bus'] not in {
            'no'
        }
    elif 'psv' in tags:
        access_designated = access_valid = tags['psv'] not in {
            'no'
        }
    elif 'motor_vehicle' in tags:
        access_valid = tags['motor_vehicle'] not in {
            'private',
            'customers',
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
        (service_valid or access_designated),
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


def is_bus_related(tags: dict[str, str]) -> bool:
    bus_valid = tags.get('bus', 'no') in {
        'yes'
    }

    return bus_valid


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


def preprocess_elements(elements: Iterable[dict]) -> Sequence[dict]:
    # deduplicate
    map = {(e['type'], e['id']): e for e in elements}
    result = tuple(map.values())

    # extract center
    for e in result:
        if 'center' in e:
            e['lat'] = e['center']['lat']
            e['lon'] = e['center']['lon']

    return result


def create_bus_stop_collections(bus_stops: list[FetchRelationBusStop]) -> list[FetchRelationBusStopCollection]:
    # 1. group by area
    # 2. group by name in area
    # 3. discard unnamed if in area with named
    # 4. for each named group, pick best platform and best stop

    if not bus_stops:
        return []

    search_latLng = BUS_COLLECTION_SEARCH_AREA / 111_111
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
            name_groups[bus_stop.groupName].append(bus_stop)

        # discard unnamed if in area with named
        if len(name_groups) > 1:
            name_groups.pop('', None)

        # expand non-number suffixed groups to number suffixed groups if needed
        prefix_map = defaultdict(list)

        for name_group_key, name_group in name_groups.items():
            parts = name_group_key.split(' ')

            while len(parts) > 1 and parts[-1].isdecimal():
                parts.pop()
                prefix_map[' '.join(parts)].append(name_group_key)

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

            def pick_best(elements: list[FetchRelationBusStop], *, limit_else: bool) -> tuple[Sequence[FetchRelationBusStop], bool]:
                if not elements:
                    return tuple(), False

                elements_explicit = tuple(e for e in elements if e.highway == 'bus_stop')

                if elements_explicit:
                    return elements_explicit, True

                elements_implicit = tuple(e for e in elements if e.highway != 'bus_stop')

                return ((elements_implicit[0],) if limit_else else elements_implicit), False

            best_platforms, platforms_explicit = pick_best(platforms, limit_else=True)
            best_stops, stops_explicit = pick_best(stops, limit_else=False)

            if platforms_explicit and stops_explicit:
                print(f'🚧 Warning: Unexpected explicit platforms and stops for {name_group_key}')

            if platforms_explicit:
                if len(stops) >= 2:
                    stops_tree = BallTree(tuple(radians_tuple(stop.latLng) for stop in stops), metric='haversine')

                    query_distances, query_indices = stops_tree.query(
                        tuple(radians_tuple(best_platform.latLng) for best_platform in best_platforms),
                        k=min(len(stops), len(best_platforms)),
                        return_distance=True,
                        sort_results=True)

                    if len(stops) < len(best_platforms):
                        query_stops = (stops[i] for i in query_indices[:, 0])
                    else:
                        assigned_stops = set()
                        platform_stops = [None] * len(best_platforms)

                        sorted_stops = sorted(
                            (dist, plat_idx, stop_idx)
                            for plat_idx, (dists, stop_indices) in enumerate(zip(query_distances, query_indices))
                            for dist, stop_idx in zip(dists, stop_indices))

                        for _, plat_idx, stop_idx in sorted_stops:
                            # skip if the stop is already assigned
                            if stop_idx in assigned_stops:
                                continue

                            # skip if the platform already has a stop
                            if platform_stops[plat_idx] is not None:
                                continue

                            platform_stops[plat_idx] = stops[stop_idx]
                            assigned_stops.add(stop_idx)

                            # break if all platforms have a stop
                            if len(assigned_stops) == len(best_platforms):
                                break

                        query_stops = platform_stops

                elif len(stops) == 1:
                    query_stops = (stops[0],) * len(best_platforms)
                else:
                    query_stops = (None,) * len(best_platforms)

                for best_platform, best_stop in zip(best_platforms, query_stops):
                    collections.append(FetchRelationBusStopCollection(
                        platform=best_platform,
                        stop=best_stop))

                continue

            assert len(best_platforms) <= 1

            if stops_explicit:
                if len(best_stops) <= 1:
                    best_platform = best_platforms[0] if best_platforms else None

                    for best_stop in best_stops:
                        collections.append(FetchRelationBusStopCollection(
                            platform=best_platform,
                            stop=best_stop))
                else:
                    for best_stop in best_stops:
                        collections.append(FetchRelationBusStopCollection(
                            platform=None,
                            stop=best_stop))

                continue

            if best_platforms:
                for best_platform in best_platforms:
                    collections.append(FetchRelationBusStopCollection(
                        platform=best_platform,
                        stop=None))

                continue

            if best_stops:
                for best_stop in best_stops:
                    collections.append(FetchRelationBusStopCollection(
                        platform=None,
                        stop=best_stop))

                continue

    return collections


def optimize_cells_and_get_bbs(cells: Sequence[Cell], *, start_horizontal: bool) -> tuple[Sequence[BoundingBox], Sequence[BoundingBox]]:
    def merge(sorted: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
        result = []
        current = sorted[0]

        for next in sorted[1:]:
            # merge horizontally
            if current[2] + 1 == next[0] and current[1] == next[1] and current[3] == next[3]:
                current = (current[0], current[1], next[2], current[3])

            # merge vertically
            elif current[3] + 1 == next[1] and current[0] == next[0] and current[2] == next[2]:
                current = (current[0], current[1], current[2], next[3])

            # add to merged cells if cells can't be merged
            else:
                result.append(current)
                current = next

        # add the last cell
        result.append(current)

        return result

    cells_bounds = ((c.x, c.y, c.x, c.y) for c in cells)

    if start_horizontal:
        cells_bounds = sorted(cells_bounds, key=lambda c: (c[1], c[0]))
    else:
        cells_bounds = sorted(cells_bounds, key=lambda c: (c[0], c[1]))

    cells_bounds = merge(cells_bounds)

    if start_horizontal:
        cells_bounds = sorted(cells_bounds, key=lambda c: (c[0], c[1]))
    else:
        cells_bounds = sorted(cells_bounds, key=lambda c: (c[1], c[0]))

    cells_bounds = merge(cells_bounds)

    bbs = tuple(BoundingBox.from_grid_cell(*c) for c in cells_bounds)

    return bbs, tuple(bb.extend(unit_degrees=DOWNLOAD_RELATION_GRID_CELL_EXPAND) for bb in bbs)


def get_download_triggers(bbc: BoundingBoxCollection, cells: Sequence[Cell], ways: dict[ElementId, FetchRelationElement]) -> dict[ElementId, Sequence[tuple[int, int]]]:
    cells_set = frozenset(cells)
    result: dict[ElementId, Sequence[Cell]] = {}

    for way_id, way in ways.items():
        way_new_cells = set()

        for latLng in way.latLngs:
            if bbc.contains(latLng):
                continue

            new_cells = BoundingBox(
                minlat=latLng[0], minlon=latLng[1],
                maxlat=latLng[0], maxlon=latLng[1]) \
                .get_grid_cells(expand=1)  # 3x3 grid

            way_new_cells |= new_cells - cells_set

        if way_new_cells:
            result[way_id] = tuple(way_new_cells)

    return dict(result)


# TODO: check data freshness
class Overpass:
    def __init__(self):
        pass

    def _get_http_client(self) -> httpx.AsyncClient:
        return get_http_client(OVERPASS_API_INTERPRETER)

    @cached(TTLCache(maxsize=1024, ttl=7200))  # 2 hours
    async def _query_relation_history_post(self, session: str, query: str, timeout: float) -> list[list[dict]]:
        async with self._get_http_client() as http:
            r = await http.post('', data={'data': query}, timeout=timeout * 2)
            r.raise_for_status()

        elements: list[dict] = r.json()['elements']
        return split_by_count(elements)

    async def _query_relation_history(self, relation_id: int, download_hist: DownloadHistory) -> tuple[list[list[dict]], BoundingBoxCollection]:
        all_elements_split = None
        all_bbs = []

        for cells in download_hist.history:
            hor_bbs_t = optimize_cells_and_get_bbs(cells, start_horizontal=True)
            ver_bbs_t = optimize_cells_and_get_bbs(cells, start_horizontal=False)

            # pick more optimal cells
            cell_bbs_t = hor_bbs_t if len(hor_bbs_t) <= len(ver_bbs_t) else ver_bbs_t
            cell_bbs, cell_bbs_expand = cell_bbs_t
            all_bbs.extend(cell_bbs)

            print(f'[OVERPASS] Downloading {len(cell_bbs)} cells for relation {relation_id}')

            timeout = 180
            query = build_bus_query(cell_bbs, cell_bbs_expand, timeout)
            elements_split = await self._query_relation_history_post(download_hist.session, query, timeout)

            if all_elements_split is None:
                all_elements_split = elements_split
            else:
                for i, elements in enumerate(elements_split):
                    all_elements_split[i].extend(elements)

        bbc = BoundingBoxCollection(all_bbs)

        return all_elements_split, bbc

    @cached(TTLCache(maxsize=128, ttl=60))
    async def query_relation(self, relation_id: int, download_hist: DownloadHistory | None, download_targets: Sequence[Cell] | None) -> tuple[BoundingBox, DownloadHistory, dict[ElementId, Sequence[tuple[int, int]]], dict[ElementId, FetchRelationElement], dict[int, list[ElementId]], list[FetchRelationBusStopCollection]]:
        if download_targets is None:
            timeout = 60
            query = build_bb_query(relation_id, timeout)

            async with self._get_http_client() as http:
                r = await http.post('', data={'data': query}, timeout=timeout * 2)
                r.raise_for_status()

            elements: list[dict] = r.json()['elements']

            relation_way_members = set(e['id'] for e in elements)
            union_grid_cells_set: set[Cell] = set()

            for way in elements:
                union_grid_cells_set.update(BoundingBox(
                    minlat=way['bounds']['minlat'],
                    minlon=way['bounds']['minlon'],
                    maxlat=way['bounds']['maxlat'],
                    maxlon=way['bounds']['maxlon'],
                )
                    .extend(DOWNLOAD_RELATION_WAY_BB_EXPAND)
                    .get_grid_cells())

            union_grid_cells = tuple(union_grid_cells_set)
        else:
            # in merge mode, members are set by the client
            relation_way_members = set()

            union_grid_cells = download_targets

        if not union_grid_cells:
            raise ValueError('No grid cells to download')

        if download_hist is None:
            download_hist = DownloadHistory(session=secrets.token_urlsafe(16), history=(union_grid_cells,))
        else:
            download_hist = replace(download_hist, history=download_hist.history + (union_grid_cells,))

        elements_split, bbc = await self._query_relation_history(relation_id, download_hist)

        maybe_road_elements = elements_split[0]
        maybe_road_elements = preprocess_elements(maybe_road_elements)
        node_elements = elements_split[1]
        node_elements = preprocess_elements(node_elements)

        bus_elements = elements_split[2]

        stop_area_relations = elements_split[3]
        stop_area_platform_elements = elements_split[4]
        stop_area_stop_position_elements = elements_split[5]

        merge_relations_tags(stop_area_relations, stop_area_platform_elements,
                             role='platform', public_transport='platform')
        merge_relations_tags(stop_area_relations, stop_area_stop_position_elements,
                             role='stop', public_transport='stop_position')

        road_elements = tuple(
            e for e in maybe_road_elements
            if is_road(e['tags']))

        nodes_map = {e['id']: e for e in node_elements}

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

        bus_elements_ex = chain(stop_area_platform_elements, stop_area_stop_position_elements, bus_elements)
        bus_elements_ex = preprocess_elements(bus_elements_ex)
        bus_elements_ex = (
            e for e in bus_elements_ex
            if is_bus_related(e['tags']) or not is_rail_related(e['tags']))

        bus_stops = tuple(FetchRelationBusStop.from_data(e) for e in bus_elements_ex)
        bus_stop_collections = create_bus_stop_collections(bus_stops)
        bus_stop_collections = tuple(
            c for c in bus_stop_collections
            if bbc.contains(c.best.latLng))

        global_bb = BoundingBox(*bbc.idx.bounds)
        download_triggers = get_download_triggers(bbc, union_grid_cells, ways)

        return global_bb, download_hist, download_triggers, ways, id_map, bus_stop_collections

    @cached(TTLCache(maxsize=128, ttl=60))
    async def query_parents(self, way_ids_set: frozenset[int]) -> QueryParentsResult:
        timeout = 60
        query = build_parents_query(way_ids_set, timeout)

        async with self._get_http_client() as http:
            r = await http.post('', data={'data': query}, timeout=timeout * 2)
            r.raise_for_status()

        data: dict[str, list[dict]] = xmltodict.parse(
            r.text,
            postprocessor=postprocessor,
            force_list=('relation', 'way', 'member', 'tag', 'nd'))['osm']

        relations = data.get('relation', [])
        id_relations_map = defaultdict(list)

        for relation in relations:
            members = relation['member'] = relation.get('member', [])
            tags = relation['tag'] = relation.get('tag', [])

            if len(members) <= 1:
                continue

            for member in members:
                if member['@type'] == 'way' and member['@ref'] in way_ids_set:
                    id_relations_map[member['@ref']].append(relation)

        # unique relations
        for way_id, relations in id_relations_map.items():
            id_relations_map[way_id] = list({r['@id']: r for r in relations}.values())

        ways = data.get('way', [])
        ways_map = {w['@id']: w for w in ways}

        return QueryParentsResult(
            id_relations_map=id_relations_map,
            ways_map=ways_map)
