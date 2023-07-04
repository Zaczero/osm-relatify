import asyncio
import itertools
import math
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from itertools import chain
from typing import NamedTuple, Self, Union

from models.element_id import ElementId
from models.fetch_relation import (FetchRelationBusStopCollection,
                                   FetchRelationElement)
from models.final_route import FinalRoute, FinalRouteWay
from relation_builder import SortedBusEntry, sort_bus_on_path
from utils import haversine_distance, print_run_time

BOOL_START = True
BOOL_END = False

VISITED_LIMIT = 2
MAX_LOOP_LENGTH = 1000
MAX_AFTER_FINISH_LENGTH = 1000


class GraphKey(NamedTuple):
    way_id: ElementId
    is_start: bool


class GraphValue(NamedTuple):
    intersection_id: int
    connected_to: tuple[GraphKey, ...]


class StackElement(NamedTuple):
    path: tuple[GraphKey, ...]
    visited: dict[GraphKey, int]
    visited_bus_stops: dict[ElementId, int]
    almost_visited_bus_stops: dict[ElementId, int]
    intersection_bus_stops_snapshot: dict[int, tuple[GraphKey, int]]
    length: float
    complete_path: set[ElementId]
    complete_length: float
    angle_sum: float = 0
    loop_length: float = 0
    after_finish_length: float = 0
    roundabout_enter: GraphKey | None = None


class BestPath(NamedTuple):
    path: tuple[GraphKey, ...]
    visited_bus_stops: dict[ElementId, int]
    bus_stops_count: int
    almost_bus_stops_count: int
    length: float
    complete_path: set[ElementId]
    complete_length: float
    angle_sum: float

    @classmethod
    def zero(cls) -> Self:
        return cls(
            path=(),
            visited_bus_stops={},
            bus_stops_count=0,
            almost_bus_stops_count=0,
            length=0,
            complete_path=set(),
            complete_length=0,
            angle_sum=0)

    def select_best(self, other: Self, ways: dict[ElementId, FetchRelationElement]) -> Self:
        # more bus stops
        if self.bus_stops_count < other.bus_stops_count:
            return other
        if self.bus_stops_count > other.bus_stops_count:
            return self

        if self.almost_bus_stops_count < other.almost_bus_stops_count:
            return other
        if self.almost_bus_stops_count > other.almost_bus_stops_count:
            return self

        complete_length_diff = other.complete_length - self.complete_length

        # avoid floating point errors, also, ignore small differences
        # length is in meters
        if abs(complete_length_diff) < 0.1:
            complete_length_diff = 0

        # more complete
        if complete_length_diff > 0:
            return other
        if complete_length_diff < 0:
            return self

        length_diff = other.length - self.length

        # avoid floating point errors, also, ignore small differences
        # length is in meters
        if abs(length_diff) < 0.1:
            length_diff = 0

        # shorter path
        if length_diff < 0:
            return other
        if length_diff > 0:
            return self

        # simpler angles
        if self.angle_sum > other.angle_sum:
            return other
        if self.angle_sum < other.angle_sum:
            return self

        # paths are equal
        return self


class BestPathCollection(NamedTuple):
    invalid: BestPath
    valid: BestPath

    def merge(self, other: Self, ways: dict[ElementId, FetchRelationElement]) -> Self:
        return BestPathCollection(
            invalid=self.invalid.select_best(other.invalid, ways),
            valid=self.valid.select_best(other.valid, ways))


def get_way_endpoints(latLngs: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    return latLngs[0], latLngs[-1]


def build_graph(ways: dict[ElementId, FetchRelationElement]) -> dict[GraphKey, GraphValue]:
    graph: dict[GraphKey, Union[list[GraphKey], GraphValue]] = {}

    for way_id, way in ways.items():
        start, end = get_way_endpoints(way.latLngs)
        start_key, stop_key = (way_id, BOOL_START), (way_id, BOOL_END)

        def get_neighbors_at(latLng: tuple[float, float]) -> list[GraphKey]:
            neighbors = []

            for connected_way_id in way.connectedTo:
                connected_way = ways.get(connected_way_id, None)

                # skip non-member ways
                if not connected_way:
                    continue

                connected_start, connected_end = get_way_endpoints(connected_way.latLngs)

                if latLng == connected_start:
                    neighbors.append(GraphKey(connected_way_id, BOOL_START))
                elif latLng == connected_end and not connected_way.oneway:
                    neighbors.append(GraphKey(connected_way_id, BOOL_END))
                else:
                    # connected via other endpoint
                    continue

            return neighbors

        graph[start_key] = get_neighbors_at(start)
        graph[stop_key] = get_neighbors_at(end)

    convert_keys = set(graph.keys())

    for intersection_num in itertools.count():
        if not convert_keys:
            break

        key = convert_keys.pop()
        neighbors = graph[key]
        graph[key] = GraphValue(intersection_num, tuple(neighbors))

        for neighbor in neighbors:
            if neighbor in convert_keys:
                # normal convert
                convert_keys.remove(neighbor)
                graph[neighbor] = GraphValue(intersection_num, tuple(graph[neighbor]))
            else:
                # merge convert (happens due to oneway)
                graph[neighbor] = graph[neighbor]._replace(intersection_id=intersection_num)

    return graph


def angle_between_ways(latLngs1: list[tuple[float, float]], latLngs2: list[tuple[float, float]]) -> float:
    start1, end1 = get_way_endpoints(latLngs1)
    start2, end2 = get_way_endpoints(latLngs2)

    # consider very end segments for angle calculation
    if end1 == start2:
        start1 = latLngs1[-2]
        end2 = latLngs2[1]

        d12 = haversine_distance(start1, end1)
        d23 = haversine_distance(end1, end2)
        d13 = haversine_distance(start1, end2)

    elif end1 == end2:
        start1 = latLngs1[-2]
        start2 = latLngs2[-2]

        d12 = haversine_distance(start1, end1)
        d23 = haversine_distance(end1, start2)
        d13 = haversine_distance(start1, start2)

    elif start1 == start2:
        end1 = latLngs1[1]
        end2 = latLngs2[1]

        d12 = haversine_distance(start1, end1)
        d23 = haversine_distance(end1, end2)
        d13 = haversine_distance(start1, end2)

    elif start1 == end2:
        end1 = latLngs1[1]
        start2 = latLngs2[-2]

        d12 = haversine_distance(start1, end1)
        d23 = haversine_distance(end1, start2)
        d13 = haversine_distance(start1, start2)

    else:
        raise Exception('Ways are not connected')

    # law of cosines
    cos_angle = (d12**2 + d23**2 - d13**2) / (2 * d12 * d23)
    angle = math.degrees(math.acos(min(max(cos_angle, -1), 1)))

    return angle


def select_neighbors(way: FetchRelationElement, neighbors: list[GraphKey], ways: dict[ElementId, FetchRelationElement], visited: set[GraphKey]) -> list[tuple[GraphKey, float]]:
    new_neighbors = [
        neighbor for neighbor in neighbors
        if visited.get(neighbor, 0) < VISITED_LIMIT]

    if not new_neighbors:
        return []
    elif len(new_neighbors) == 1:
        return [(new_neighbors[0], 0)]

    angles = [
        (angle_between_ways(way.latLngs, ways[neighbor.way_id].latLngs), neighbor)
        for neighbor in new_neighbors]

    # the angle difference from the straight path
    # TODO: support 0-180 range by utilizing is_start
    angle_differences = [
        (neighbor, 90 - abs(90 - angle))
        for angle, neighbor in angles]

    return angle_differences


def get_bus_stops_at(neighbor: GraphKey, id_sorted_bus_map: dict[ElementId, list[SortedBusEntry]]) -> tuple[list[SortedBusEntry], list[SortedBusEntry]]:
    neighbor_is_forward = neighbor.is_start

    visited = []
    almost_visited = []

    for sorted_bus in id_sorted_bus_map.get(neighbor.way_id, []):
        if sorted_bus.right_hand_side is None or neighbor_is_forward == sorted_bus.right_hand_side:
            visited.append(sorted_bus)
        else:
            almost_visited.append(sorted_bus)

    if not neighbor_is_forward:
        visited.reverse()
        almost_visited.reverse()

    return visited, almost_visited


def modified_dfs_worker(graph: dict[GraphKey, GraphValue], ways: dict[ElementId, FetchRelationElement], end_way: ElementId, id_sorted_bus_map: dict[ElementId, list[SortedBusEntry]], stack: list[StackElement], best_path: BestPathCollection, max_iter: int) -> tuple[list[StackElement], BestPathCollection]:
    message_ref = [f'Worker with {len(stack)} stack size']

    with print_run_time(message_ref):
        for current_iter in range(1, max_iter + 1):
            if not stack:
                break

            s = stack.pop()

            current_key = s.path[-1]
            exit_at_key = current_key._replace(is_start=not current_key.is_start)

            current_best_path = BestPath(
                s.path,
                visited_bus_stops=s.visited_bus_stops | s.almost_visited_bus_stops,
                bus_stops_count=len(s.visited_bus_stops),
                almost_bus_stops_count=len(s.almost_visited_bus_stops),
                length=s.length,
                complete_path=s.complete_path,
                complete_length=s.complete_length,
                angle_sum=s.angle_sum)

            if current_key.way_id == end_way:
                if (replace := best_path.valid.select_best(current_best_path, ways)) == current_best_path:
                    best_path = best_path._replace(valid=replace)
            else:
                if (replace := best_path.invalid.select_best(current_best_path, ways)) == current_best_path:
                    best_path = best_path._replace(invalid=replace)

            current_way = ways[current_key.way_id]
            neighbors = graph[exit_at_key].connected_to
            valid_neighbors = select_neighbors(current_way, neighbors, ways, s.visited)

            intersection_id = graph[exit_at_key].intersection_id

            if (t := s.intersection_bus_stops_snapshot.get(intersection_id, None)) is not None:
                intersection_entered_at, intersection_bus_stops_count = t
            else:
                intersection_entered_at = None
                intersection_bus_stops_count = None

            if intersection_entered_at is None or intersection_bus_stops_count < len(s.visited_bus_stops) + len(s.almost_visited_bus_stops):
                new_intersection_bus_stops_snapshot_changed = True
                new_intersection_bus_stops_snapshot = s.intersection_bus_stops_snapshot.copy()
                new_intersection_bus_stops_snapshot[intersection_id] = (
                    exit_at_key, len(s.visited_bus_stops) + len(s.almost_visited_bus_stops))
            else:
                new_intersection_bus_stops_snapshot_changed = False
                new_intersection_bus_stops_snapshot = s.intersection_bus_stops_snapshot

            for neighbor, neighbor_angle in valid_neighbors:
                neighbor_way = ways[neighbor.way_id]

                new_path = s.path + (neighbor,)
                new_visited = s.visited.copy()

                new_neighbor_visited = new_visited.get(neighbor, 0) + 1
                new_visited[neighbor] = new_neighbor_visited

                visited_bus_stops, almost_visited_bus_stops = get_bus_stops_at(neighbor, id_sorted_bus_map)

                if visited_bus_stops or almost_visited_bus_stops:
                    new_visited_bus_stops = s.visited_bus_stops.copy()
                    new_almost_visited_bus_stops = s.almost_visited_bus_stops.copy()

                    for b in visited_bus_stops:
                        new_visited_bus_stops.setdefault(b.bus_stop_collection.best.id, len(new_path))

                    for b in almost_visited_bus_stops:
                        new_almost_visited_bus_stops.setdefault(b.bus_stop_collection.best.id, len(new_path))

                    new_almost_visited_bus_stops = {
                        k: v
                        for k, v in new_almost_visited_bus_stops.items()
                        if k not in new_visited_bus_stops}
                else:
                    new_visited_bus_stops = s.visited_bus_stops
                    new_almost_visited_bus_stops = s.almost_visited_bus_stops

                if not new_intersection_bus_stops_snapshot_changed and len(neighbors) > 1:
                    # allow only going back if there are no new bus stops (to prevent useless loops)
                    if neighbor != intersection_entered_at:
                        continue

                new_length = s.length + neighbor_way.length

                if neighbor_way.id not in s.complete_path:
                    new_complete_path = s.complete_path.copy()
                    new_complete_path.add(neighbor_way.id)
                    new_complete_length = s.complete_length + neighbor_way.length
                else:
                    new_complete_path = s.complete_path
                    new_complete_length = s.complete_length

                # roundabout looping and exits are free
                if current_way.roundabout:
                    new_angle_sum = s.angle_sum
                else:
                    new_angle_sum = s.angle_sum + neighbor_angle

                if new_neighbor_visited > 1 and new_neighbor_visited >= s.visited[current_key]:
                    new_loop_length = s.loop_length + neighbor_way.length
                else:
                    new_loop_length = 0

                # stop path if too long loop
                if new_loop_length > MAX_LOOP_LENGTH:
                    continue

                if s.after_finish_length > 0 or neighbor.way_id == end_way:
                    new_after_finish_length = s.after_finish_length + neighbor_way.length
                else:
                    new_after_finish_length = 0

                # stop path if too long after finish
                if new_after_finish_length > MAX_AFTER_FINISH_LENGTH:
                    continue

                if neighbor_way.roundabout:
                    if s.roundabout_enter:
                        # stop path if looping in roundabout
                        if s.roundabout_enter == neighbor:
                            continue
                        else:
                            new_roundabout_enter = s.roundabout_enter
                    else:
                        new_roundabout_enter = neighbor
                else:
                    new_roundabout_enter = None

                stack.append(StackElement(
                    path=new_path,
                    visited=new_visited,
                    visited_bus_stops=new_visited_bus_stops,
                    almost_visited_bus_stops=new_almost_visited_bus_stops,
                    intersection_bus_stops_snapshot=new_intersection_bus_stops_snapshot,
                    length=new_length,
                    complete_path=new_complete_path,
                    complete_length=new_complete_length,
                    angle_sum=new_angle_sum,
                    loop_length=new_loop_length,
                    after_finish_length=new_after_finish_length,
                    roundabout_enter=new_roundabout_enter))

        message_ref[0] += f' and {current_iter} iterations'

    return stack, best_path


async def modified_dfs(graph: dict[GraphKey, GraphValue], ways: dict[ElementId, FetchRelationElement], start_way: ElementId, end_way: ElementId, id_sorted_bus_map: dict[ElementId, list[SortedBusEntry]], executor: ProcessPoolExecutor, n_processes: int) -> BestPath:
    start_start_key = GraphKey(start_way, BOOL_START)
    start_end_key = GraphKey(start_way, BOOL_END)

    def init_stack_element(key: GraphKey) -> StackElement:
        intersection_id = graph[key].intersection_id
        visited_bus_stops, almost_visited_bus_stops = get_bus_stops_at(key, id_sorted_bus_map)

        return StackElement(
            path=(key,),
            visited={key: 1},
            visited_bus_stops={b.bus_stop_collection.best.id: 1 for b in visited_bus_stops},
            almost_visited_bus_stops={b.bus_stop_collection.best.id: 1 for b in almost_visited_bus_stops},
            intersection_bus_stops_snapshot={
                intersection_id: (key, len(visited_bus_stops) + len(almost_visited_bus_stops))},
            length=ways[start_way].length,
            complete_path={key.way_id},
            complete_length=ways[start_way].length)

    stack: list[StackElement] = [
        init_stack_element(start_start_key),
        init_stack_element(start_end_key)]

    best_path = BestPathCollection(
        valid=BestPath.zero(),
        invalid=BestPath.zero())

    # for reference:
    # AMD Ryzen 9 5950X: 10,000 iterations in ~ 0.1s
    sync_max_iter = 3000  # .03s
    async_max_iter = 10000  # .10s

    # run a few iterations synchronously to get a head start
    stack, best_path = modified_dfs_worker(graph, ways, end_way, id_sorted_bus_map, stack, best_path,
                                           max_iter=sync_max_iter)

    tasks = []

    async def worker(stack_slice: list[StackElement], best_path: BestPathCollection, max_iter: int) -> tuple[list[StackElement], BestPathCollection]:
        loop = asyncio.get_running_loop()

        return await loop.run_in_executor(
            executor,
            modified_dfs_worker,
            graph, ways, end_way, id_sorted_bus_map, stack_slice, best_path, max_iter)

    while stack or tasks:
        stack_slices_len_target = n_processes - len(tasks)
        stack_slice_size_target, remainder = divmod(len(stack), stack_slices_len_target)
        stack_slices: list[list[StackElement]] = []

        for i in range(stack_slices_len_target):
            current_slice_size = stack_slice_size_target + (1 if i < remainder else 0)

            if current_slice_size == 0:
                break

            stack_slices.append(stack[:current_slice_size])
            stack = stack[current_slice_size:]

        assert not stack, 'Stack must be empty after slicing'

        print(f'[DEBUG] Stack slice sizes: {", ".join(str(len(stack_slice)) for stack_slice in stack_slices)}')

        tasks.extend(asyncio.create_task(worker(stack_slice, best_path, async_max_iter))
                     for stack_slice in stack_slices)

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            stack_slice, best_path_slice = task.result()
            stack += stack_slice
            best_path = best_path.merge(best_path_slice, ways)

        tasks = list(pending)

    return best_path.valid if best_path.valid.path else best_path.invalid


def finalize_route(best_path: BestPath, ways: dict[ElementId, FetchRelationElement], bus_stop_collections: list[FetchRelationBusStopCollection], tags: dict[str, str]) -> FinalRoute:
    route_ways = tuple(
        FinalRouteWay(
            way=ways[key.way_id],
            reversed_latLngs=not key.is_start)
        for key in best_path.path)

    route_latLngs_gen = (
        route_way.way.latLngs[::-1] if route_way.reversed_latLngs else route_way.way.latLngs
        for route_way in route_ways)

    route_latLngs = tuple(chain.from_iterable(
        latLngs if i == 0 else latLngs[1:]
        for i, latLngs in enumerate(route_latLngs_gen)))

    route_latLngs_set = set(route_latLngs)

    id_collection_map = {collection.best.id: collection for collection in bus_stop_collections}

    route_bus_stops = []

    for stop_id, _ in sorted(best_path.visited_bus_stops.items(), key=lambda x: x[1]):
        collection = id_collection_map[stop_id]

        if collection.stop is not None and collection.stop.latLng not in route_latLngs_set:
            collection = replace(collection, stop=None)

        if collection.platform is None and collection.stop is None:
            continue

        route_bus_stops.append(collection)

    return FinalRoute(
        ways=route_ways,
        latLngs=route_latLngs,
        busStops=tuple(route_bus_stops),
        tags=tags)


async def calc_bus_route(ways_members: dict[ElementId, FetchRelationElement], start_way: ElementId, end_way: ElementId, bus_stop_collections: list[FetchRelationBusStopCollection], tags: dict[str, str], executor: ProcessPoolExecutor, n_processes: int) -> FinalRoute:
    with print_run_time('Sorting bus stops'):
        sorted_buses = sort_bus_on_path(bus_stop_collections, ways_members.values())

    id_sorted_bus_map: dict[ElementId, list[SortedBusEntry]] = defaultdict(list)

    for sorted_bus in sorted_buses:
        id_sorted_bus_map[sorted_bus.neighbor_id].append(sorted_bus)

    with print_run_time('Building graph'):
        graph = build_graph(ways_members)

    with print_run_time('Calculating route'):
        best_path = await modified_dfs(graph, ways_members, start_way, end_way, id_sorted_bus_map, executor, n_processes)

    return finalize_route(best_path, ways_members, bus_stop_collections, tags)
