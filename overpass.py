from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from itertools import chain
from typing import NamedTuple

import xmltodict
from asyncache import cached
from cachetools import TTLCache
from fastapi import HTTPException
from starlette import status

from bus_collection_builder import build_bus_stop_collections
from config import DOWNLOAD_RELATION_GRID_CELL_EXPAND, DOWNLOAD_RELATION_WAY_BB_EXPAND, OVERPASS_API_INTERPRETER
from models.bounding_box import BoundingBox
from models.bounding_box_collection import BoundingBoxCollection
from models.download_history import Cell, DownloadHistory
from models.element_id import ElementId, element_id
from models.fetch_relation import FetchRelationBusStop, FetchRelationBusStopCollection, FetchRelationElement
from utils import HTTP
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
    return f'[out:json][timeout:{timeout}];rel({relation_id});way(r);out ids bb qt;'


def build_query(
    cell_bbs: Sequence[BoundingBox],
    cell_bbs_expanded: Sequence[BoundingBox],
    timeout: int,
    route_type: str,
) -> str:
    if route_type == 'bus':
        return (
            f'[out:json][timeout:{timeout}];'
            f'(' + ''.join(f'way[highway][!footway]({bb});' for bb in cell_bbs) + ');'
            'out body qt;'
            'out count;'
            '>;'
            'out skel qt;'
            'out count;'
            '(' + ''.join(f'node[highway=turning_circle]({bb});' for bb in cell_bbs) + ');'
            'out tags qt;'
            'out count;'
            + ''.join(
                f'node[highway=bus_stop][public_transport=platform][name]({bb});'
                f'out tags center qt;'
                f'nwr[highway=platform][public_transport=platform][name]({bb});'
                f'out tags center qt;'
                f'nwr[highway=platform][public_transport=platform][ref]({bb});'
                f'out tags center qt;'
                f'node[public_transport=stop_position][name]({bb});'
                f'out tags center qt;'
                for bb in cell_bbs_expanded
            )
            + 'out count;'
            '(' + ''.join(f'rel[public_transport=stop_area]({bb});' for bb in cell_bbs_expanded) + ')->.r;'
            '.r out body qt;'
            '.r out count;'
            'node(r.r:platform);'
            'out tags center qt;'
            'way(r.r:platform);'
            'out tags center qt;'
            'rel(r.r:platform);'
            'out tags center qt;'
            'out count;'
            'node(r.r:stop);'
            'out tags center qt;'
            'out count;'
        )

    if route_type == 'tram':
        return (
            f'[out:json][timeout:{timeout}];'
            f'(' + ''.join(f'way[railway=tram]({bb});' for bb in cell_bbs) + ');'
            'out body qt;'
            'out count;'
            '>;'
            'out skel qt;'
            'out count;'
            '(' + ''.join(f'node[highway=turning_circle]({bb});' for bb in cell_bbs) + ');'
            'out tags qt;'
            'out count;'
            + ''.join(
                f'node[railway=tram_stop][public_transport=stop_position][name]({bb});'
                f'out tags center qt;'
                f'nwr[railway=platform][public_transport=platform][name]({bb});'
                f'out tags center qt;'
                f'nwr[railway=platform][public_transport=platform][ref]({bb});'
                f'out tags center qt;'
                f'nwr[tram][public_transport=platform][name]({bb});'
                f'out tags center qt;'
                for bb in cell_bbs_expanded
            )
            + 'out count;'
            '(' + ''.join(f'rel[public_transport=stop_area]({bb});' for bb in cell_bbs_expanded) + ')->.r;'
            '.r out body qt;'
            '.r out count;'
            'node(r.r:platform);'
            'out tags center qt;'
            'way(r.r:platform);'
            'out tags center qt;'
            'rel(r.r:platform);'
            'out tags center qt;'
            'out count;'
            'node(r.r:stop);'
            'out tags center qt;'
            'out count;'
        )

    raise NotImplementedError(f'Unsupported route type {route_type!r}')


def build_parents_query(way_ids: Iterable[int], timeout: int) -> str:
    def _parents(way_id: int) -> str:
        return f'way({way_id});(rel(bw);.r;)->.r;'

    return (
        f'[out:xml][timeout:{timeout}];'
        f'._->.r;' + ''.join(_parents(way_id) for way_id in way_ids) + '.r out meta qt;'
        'way(r.r);'
        'out skel qt;'
    )


def is_routable(tags: dict[str, str], route_type: str) -> bool:
    if route_type == 'bus':
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

        highway_designated_valid = tags['highway'] in {
            'pedestrian',
        }

        service_valid = tags.get('service', 'no') not in {
            'driveway',
            'parking_aisle',
            'alley',
            'emergency_access',
        }

        access_designated = False
        access_valid = True

        if 'bus:conditional' in tags:
            access_designated = access_valid = True
        elif 'bus' in tags:
            access_designated = access_valid = tags['bus'] not in {'no'}
        elif 'psv' in tags:
            access_designated = access_valid = tags['psv'] not in {'no'}
        elif 'motor_vehicle' in tags:
            access_valid = tags['motor_vehicle'] not in {'private', 'customers', 'no'}
        elif 'access' in tags:
            access_valid = tags['access'] not in {'private', 'customers', 'no'}

        noarea_valid = tags.get('area', 'no') in {'no'}

        return all(
            (
                (highway_valid or (highway_designated_valid and access_designated)),
                (service_valid or access_designated),
                access_valid,
                noarea_valid,
            )
        )

    if route_type == 'tram':
        # all overpass-fetched elements are routable
        return True

    raise NotImplementedError(f'Unsupported route type {route_type!r}')


def is_oneway(tags: dict[str, str]) -> bool:
    # TODO: it would be nice to support oneway=-1

    roundabout_valid = False

    if 'junction' in tags:
        roundabout_valid = tags['junction'] in {'roundabout'}

    oneway_valid = roundabout_valid

    if 'oneway:bus' in tags:
        oneway_valid = tags['oneway:bus'] in {'yes'}
    elif 'oneway:psv' in tags:
        oneway_valid = tags['oneway:psv'] in {'yes'}
    elif 'oneway' in tags:
        oneway_valid = tags['oneway'] in {'yes'}

    return oneway_valid


def is_roundabout(tags: dict[str, str]) -> bool:
    return tags.get('junction', 'no') in {'roundabout'}


def is_bus_explicit(tags: dict[str, str]) -> bool:
    return tags.get('bus') == 'yes' or tags.get('trolleybus') == 'yes'


def is_any_rail_related(tags: dict[str, str]) -> bool:
    rail_valid = 'railway' in tags
    tram_valid = tags.get('tram', 'no') in {'yes'}
    train_valid = tags.get('train', 'no') in {'yes'}
    subway_valid = tags.get('subway', 'no') in {'yes'}
    return any((rail_valid, tram_valid, train_valid, subway_valid))


def is_tram_element(tags: dict[str, str]) -> bool:
    rail_valid = 'railway' in tags
    tram_valid = tags.get('tram', 'no') in {'yes'}
    train_valid = tags.get('train', 'no') in {'yes'}
    subway_valid = tags.get('subway', 'no') in {'yes'}
    return tram_valid or (rail_valid and not train_valid and not subway_valid)


def _merge_relation_tags(element: dict, relation: dict, extra: dict) -> None:
    element['tags'] = {
        **relation.get('tags', {}),
        **element.get('tags', {}),
        **extra,
    }


def merge_relations_tags(relations: Iterable[dict], elements: Iterable[dict], role: str, public_transport: str) -> None:
    element_map = {(e['type'], e['id']): e for e in elements}

    for relation in sorted(relations, key=lambda r: r['id']):
        for member in (m for m in relation['members'] if m['role'] == role):
            platform = element_map.get((member['type'], member['ref']), None)

            if platform is None:
                print(f'🚧 Warning: Platform {member["type"]}/{member["ref"]} not found in map')
                continue

            _merge_relation_tags(platform, relation, {'public_transport': public_transport})


def _create_node_counts(ways: list[dict]) -> Counter[int]:
    node_counts: Counter[int] = Counter()
    for way in ways:
        node_counts.update(way['nodes'])
    return node_counts


def _split_way_on_intersection(way: dict, node_counts: Mapping[int, int]) -> list[list[int]]:
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


def organize_ways(ways: list[dict], turn_in_place_nodes: set[int]) -> tuple[list[dict], dict[ElementId, set[ElementId]], dict[int, list[ElementId]]]:
    node_counts = _create_node_counts(ways)
    node_to_way_map = defaultdict(set)

    split_ways: list[dict] = []
    connected_ways_map: dict[ElementId, set[ElementId]] = defaultdict(set)
    id_map = defaultdict(list)

    for way in ways:
        split_segments = _split_way_on_intersection(way, node_counts)

        for extra_num, segment in enumerate(split_segments, 1):
            extra_num = extra_num if len(split_segments) > 1 else None
            max_num = len(split_segments) if extra_num is not None else None

            split_way = {
                **way,
                'id': element_id(way['id'], extra_num=extra_num, max_num=max_num),
                'nodes': segment,
                '_turn_in_place_start': segment[0] in turn_in_place_nodes,
                '_turn_in_place_end': segment[-1] in turn_in_place_nodes,
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


def preprocess_elements(elements: Iterable[dict]) -> tuple[dict, ...]:
    # deduplicate by type/id
    result: tuple[dict, ...] = tuple({(e['type'], e['id']): e for e in elements}.values())
    # extract center
    for e in result:
        center: dict | None = e.get('center')
        if center is not None:
            e.update(center)
    return result


def optimize_cells_and_get_bbs(
    cells: Sequence[Cell],
    *,
    start_horizontal: bool,
) -> tuple[Sequence[BoundingBox], Sequence[BoundingBox]]:
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


def get_download_triggers(
    bbc: BoundingBoxCollection,
    cells: Sequence[Cell],
    ways: dict[ElementId, FetchRelationElement],
) -> dict[ElementId, tuple[Cell, ...]]:
    cells_set = frozenset(cells)
    result = {}

    for way_id, way in ways.items():
        way_new_cells = set()

        for latLng in way.latLngs:
            if bbc.contains(latLng):
                continue

            new_cells = BoundingBox(
                minlat=latLng[0],
                minlon=latLng[1],
                maxlat=latLng[0],
                maxlon=latLng[1],
            ).get_grid_cells(expand=1)  # 3x3 grid

            way_new_cells |= new_cells - cells_set

        if way_new_cells:
            result[way_id] = tuple(way_new_cells)

    return dict(result)


# TODO: check data freshness
class Overpass:
    def __init__(self):
        pass

    @cached(TTLCache(maxsize=1024, ttl=7200))  # 2 hours
    async def _query_relation_history_post(
        self,
        session: str,  # cache busting  # noqa: ARG002
        query: str,
        http_timeout: float,
    ) -> list[list[dict]]:
        r = await HTTP.post(OVERPASS_API_INTERPRETER, data={'data': query}, timeout=http_timeout * 2)
        r.raise_for_status()
        elements: list[dict] = r.json()['elements']
        return split_by_count(elements)

    async def _query_relation_history(
        self,
        relation_id: int,
        download_hist: DownloadHistory,
        route_type: str,
    ) -> tuple[list[list[dict]], BoundingBoxCollection]:
        if not download_hist.history or not all(download_hist.history):
            raise ValueError('No grid cells to download')

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
            query = build_query(cell_bbs, cell_bbs_expand, timeout, route_type)
            elements_split = await self._query_relation_history_post(download_hist.session, query, timeout)

            if all_elements_split is None:
                all_elements_split = elements_split
            else:
                for i, elements in enumerate(elements_split):
                    all_elements_split[i].extend(elements)

        bbc = BoundingBoxCollection(all_bbs)

        return all_elements_split, bbc

    @cached(TTLCache(maxsize=128, ttl=60))
    async def query_relation(
        self,
        relation_id: int,
        download_hist: DownloadHistory | None,
        download_targets: Sequence[Cell] | None,
        route_type: str,  # bus, tram...
    ) -> tuple[
        BoundingBox,
        DownloadHistory,
        dict[ElementId, tuple[Cell, ...]],
        dict[ElementId, FetchRelationElement],
        dict[int, list[ElementId]],
        list[FetchRelationBusStopCollection],
    ]:
        if download_targets is None:
            timeout = 60
            query = build_bb_query(relation_id, timeout)
            r = await HTTP.post(OVERPASS_API_INTERPRETER, data={'data': query}, timeout=timeout * 2)
            r.raise_for_status()

            elements: list[dict] = r.json()['elements']
            if not elements:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Relation is empty, which is not supported')

            relation_way_members = {e['id'] for e in elements}
            union_grid_cells_set: set[Cell] = set()

            for way in elements:
                union_grid_cells_set.update(
                    BoundingBox(
                        minlat=way['bounds']['minlat'],
                        minlon=way['bounds']['minlon'],
                        maxlat=way['bounds']['maxlat'],
                        maxlon=way['bounds']['maxlon'],
                    )
                    .extend(DOWNLOAD_RELATION_WAY_BB_EXPAND)
                    .get_grid_cells()
                )

            union_grid_cells = tuple(union_grid_cells_set)
        else:
            # in merge mode, members are set by the client
            relation_way_members = set()

            union_grid_cells = download_targets

        if download_hist is None:
            download_hist = DownloadHistory(session=DownloadHistory.make_session(), history=(union_grid_cells,))
        elif union_grid_cells:
            download_hist = replace(download_hist, history=(*download_hist.history, union_grid_cells))

        elements_split, bbc = await self._query_relation_history(relation_id, download_hist, route_type)

        maybe_road_elements = elements_split[0]
        maybe_road_elements = preprocess_elements(maybe_road_elements)
        node_elements = elements_split[1]
        node_elements = preprocess_elements(node_elements)
        turn_in_place_elements = elements_split[2]
        turn_in_place_elements = preprocess_elements(turn_in_place_elements)

        bus_elements = elements_split[3]

        stop_area_relations = elements_split[4]
        stop_area_platform_elements = elements_split[5]
        stop_area_stop_position_elements = elements_split[6]

        merge_relations_tags(
            stop_area_relations,
            stop_area_platform_elements,
            role='platform',
            public_transport='platform',
        )
        merge_relations_tags(
            stop_area_relations,
            stop_area_stop_position_elements,
            role='stop',
            public_transport='stop_position',
        )

        road_elements = tuple(e for e in maybe_road_elements if is_routable(e['tags'], route_type))

        nodes_map = {e['id']: e for e in node_elements}
        turn_in_place_nodes = {e['id'] for e in turn_in_place_elements}

        for e in road_elements:
            e['_member'] = e['id'] in relation_way_members
            e['_oneway'] = is_oneway(e['tags'])
            e['_roundabout'] = is_roundabout(e['tags'])

        road_elements, connected_ways_map, id_map = organize_ways(road_elements, turn_in_place_nodes)

        ways = {
            e['id']: FetchRelationElement(
                id=e['id'],
                member=e['_member'],
                oneway=e['_oneway'],
                roundabout=e['_roundabout'],
                nodes=e['nodes'],
                latLngs=[(nodes_map[n_id]['lat'], nodes_map[n_id]['lon']) for n_id in e['nodes']],
                connectedTo=list(connected_ways_map[e['id']]),
                turn_in_place_start=e['_turn_in_place_start'],
                turn_in_place_end=e['_turn_in_place_end'],
            )
            for e in road_elements
        }

        elements_ex = chain(stop_area_platform_elements, stop_area_stop_position_elements, bus_elements)
        elements_ex = preprocess_elements(elements_ex)
        if route_type == 'bus':
            elements_ex = (e for e in elements_ex if is_bus_explicit(e['tags']) or not is_any_rail_related(e['tags']))
        elif route_type == 'tram':
            elements_ex = (e for e in elements_ex if is_tram_element(e['tags']))

        stops = tuple(FetchRelationBusStop.from_data(e) for e in elements_ex)
        bus_stop_collections = build_bus_stop_collections(stops)
        bus_stop_collections = tuple(c for c in bus_stop_collections if bbc.contains(c.best.latLng))

        global_bb = BoundingBox(*bbc.idx.bounds)
        download_triggers = get_download_triggers(bbc, union_grid_cells, ways)

        return global_bb, download_hist, download_triggers, ways, id_map, bus_stop_collections

    @cached(TTLCache(maxsize=128, ttl=60))
    async def query_parents(self, way_ids_set: frozenset[int]) -> QueryParentsResult:
        timeout = 60
        query = build_parents_query(way_ids_set, timeout)
        r = await HTTP.post(OVERPASS_API_INTERPRETER, data={'data': query}, timeout=timeout * 2)
        r.raise_for_status()

        data: dict[str, list[dict]] = xmltodict.parse(
            r.text,
            postprocessor=postprocessor,
            force_list=('relation', 'way', 'member', 'tag', 'nd'),
        )['osm']

        relations = data.get('relation', [])
        id_relations_map = defaultdict(list)

        for relation in relations:
            members = relation['member'] = relation.get('member', [])
            # tags = relation['tag'] = relation.get('tag', [])

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
            ways_map=ways_map,
        )
