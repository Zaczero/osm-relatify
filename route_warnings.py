from dataclasses import replace
from itertools import zip_longest

from sentry_sdk import trace

from models.element_id import ElementId
from models.fetch_relation import FetchRelationBusStopCollection, FetchRelationElement
from models.final_route import FinalRoute, FinalRouteWarning, WarningSeverity
from models.relation_member import RelationMember
from relation_builder import sort_bus_on_path


@trace
def _check_for_unused_ways(route: FinalRoute, ways: dict[ElementId, FetchRelationElement]) -> FinalRouteWarning | None:
    way_ids = set(ways.keys())
    way_ids.difference_update(route_way.way.id for route_way in route.ways)
    if way_ids:
        return FinalRouteWarning(
            severity=WarningSeverity.HIGH,
            message='Some ways are not used',
            extra=tuple(way_ids),
        )


@trace
def _check_for_end_not_reached(route: FinalRoute, end_way: ElementId) -> FinalRouteWarning | None:
    if end_way not in (route_way.way.id for route_way in route.ways):
        return FinalRouteWarning(
            severity=WarningSeverity.HIGH,
            message='The stop point is not reached',
        )


@trace
def _check_for_bus_stop_far_away(
    route: FinalRoute,
    bus_stop_collections: list[FetchRelationBusStopCollection],
) -> FinalRouteWarning | None:
    threshold = 120  # meters
    sorted_ways = tuple(route_way.way for route_way in route.ways)
    sorted_bus_stops = sort_bus_on_path(bus_stop_collections, sorted_ways)
    far_way_bus_stops = tuple(stop for stop in sorted_bus_stops if stop.distance_from_neighbor > threshold)
    if far_way_bus_stops:
        return FinalRouteWarning(
            severity=WarningSeverity.LOW,
            message='Some stops are far away',
            extra=tuple(stop.bus_stop_collection.best.id for stop in far_way_bus_stops),
        )


@trace
def _check_for_bus_stop_not_reached(
    route: FinalRoute,
    bus_stop_collections: list[FetchRelationBusStopCollection],
) -> FinalRouteWarning | None:
    if len(route.busStops) == len(bus_stop_collections):
        return None
    not_reached_bus_stop_ids: set[ElementId] = {collection.best.id for collection in bus_stop_collections}
    not_reached_bus_stop_ids.difference_update(collection.best.id for collection in route.busStops)
    return FinalRouteWarning(
        severity=WarningSeverity.HIGH,
        message='Some stops are not reached',
        extra=tuple(not_reached_bus_stop_ids),
    )


@trace
def _check_for_not_enough_bus_stops(route: FinalRoute) -> FinalRouteWarning | None:
    if len(route.busStops) < 2:
        return FinalRouteWarning(
            severity=WarningSeverity.HIGH,
            message='The route has less than 2 stops',
        )


@trace
def _check_for_roundtrip_not_roundtrip(route: FinalRoute) -> FinalRouteWarning | None:
    if route.roundtrip and route.latLngs and route.latLngs[0] != route.latLngs[-1]:
        return FinalRouteWarning(
            severity=WarningSeverity.LOW,
            message='The route is not a valid roundtrip',
        )


@trace
def _check_for_members_unchanged(route: FinalRoute, relation_members: list[RelationMember]) -> FinalRouteWarning | None:
    for route_member, relation_member in zip_longest(route.members, relation_members):
        if route_member != relation_member:
            return None
    return FinalRouteWarning(
        severity=WarningSeverity.UNCHANGED,
        message='The route is unchanged',
    )


@trace
def check_for_issues(
    route: FinalRoute,
    ways: dict[ElementId, FetchRelationElement],
    start_way: ElementId,  # noqa: ARG001
    end_way: ElementId,
    bus_stop_collections: list[FetchRelationBusStopCollection],
    relation_members: list[RelationMember],
) -> FinalRoute:
    warnings = (
        _check_for_unused_ways(route, ways),
        _check_for_end_not_reached(route, end_way),
        _check_for_bus_stop_far_away(route, bus_stop_collections),
        _check_for_bus_stop_not_reached(route, bus_stop_collections),
        _check_for_not_enough_bus_stops(route),
        _check_for_roundtrip_not_roundtrip(route),
        _check_for_members_unchanged(route, relation_members),
    )
    sorted_warnings = tuple(sorted(filter(None, warnings), key=lambda warning: warning.severity.value, reverse=True))
    return replace(route, warnings=sorted_warnings)
