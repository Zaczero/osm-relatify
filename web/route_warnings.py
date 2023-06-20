from dataclasses import replace
from itertools import zip_longest

from models.element_id import ElementId
from models.fetch_relation import (FetchRelationBusStopCollection,
                                   FetchRelationElement)
from models.final_route import FinalRoute, FinalRouteWarning, WarningSeverity
from models.relation_member import RelationMember
from relation_builder import sort_bus_on_path


def _check_for_unused_ways(route: FinalRoute, ways: dict[ElementId, FetchRelationElement]) -> FinalRouteWarning | None:
    route_ids = set(map(lambda route_way: route_way.way.id, route.ways))
    way_ids = set(ways.keys())

    unused_way_ids = way_ids - route_ids

    if unused_way_ids:
        return FinalRouteWarning(
            severity=WarningSeverity.HIGH,
            message='Some ways are not used')

    return None


def _check_for_end_not_reached(route: FinalRoute, end_way: ElementId) -> FinalRouteWarning | None:
    route_ids = set(map(lambda route_way: route_way.way.id, route.ways))

    if end_way not in route_ids:
        return FinalRouteWarning(
            severity=WarningSeverity.HIGH,
            message='The stop point is not reached')

    return None


def _check_for_bus_stop_far_away(route: FinalRoute, bus_stop_collections: list[FetchRelationBusStopCollection]) -> FinalRouteWarning | None:
    threshold = 120  # meters
    sorted_ways = (route_way.way for route_way in route.ways)

    for sorted_bus in sort_bus_on_path(bus_stop_collections, sorted_ways):
        if sorted_bus.distance_from_neighbor > threshold:
            return FinalRouteWarning(
                severity=WarningSeverity.LOW,
                message='Some stops are far away')

    return None


def _check_for_bus_stop_not_reached(route: FinalRoute, bus_stop_collections: list[FetchRelationBusStopCollection]) -> FinalRouteWarning | None:
    if len(route.busStops) != len(bus_stop_collections):
        return FinalRouteWarning(
            severity=WarningSeverity.HIGH,
            message='Some stops are not reached')


def _check_for_not_enough_bus_stops(route: FinalRoute) -> FinalRouteWarning | None:
    if len(route.busStops) < 2:
        return FinalRouteWarning(
            severity=WarningSeverity.HIGH,
            message='The route has less than 2 stops')

    return None


def _check_for_members_unchanged(route: FinalRoute, relation_members: list[RelationMember]) -> FinalRouteWarning | None:
    for route_member, relation_member in zip_longest(route.members, relation_members):
        if route_member != relation_member:
            return None

    return FinalRouteWarning(
        severity=WarningSeverity.UNCHANGED,
        message='The route is unchanged')


def check_for_issues(route: FinalRoute, ways: dict[ElementId, FetchRelationElement], start_way: ElementId, end_way: ElementId, bus_stop_collections: list[FetchRelationBusStopCollection], relation_members: list[RelationMember]) -> FinalRoute:
    warnings = [
        _check_for_unused_ways(route, ways),
        _check_for_end_not_reached(route, end_way),
        _check_for_bus_stop_far_away(route, bus_stop_collections),
        _check_for_bus_stop_not_reached(route, bus_stop_collections),
        _check_for_members_unchanged(route, relation_members)]

    sorted_warnings = tuple(sorted(filter(None, warnings), key=lambda warning: warning.severity.value[1], reverse=True))

    return replace(route, warnings=sorted_warnings)
