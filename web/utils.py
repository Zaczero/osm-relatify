import time
from contextlib import contextmanager
from math import atan2, cos, radians, sin, sqrt
from typing import Generator

import httpx
from numba import njit

from config import USER_AGENT


@contextmanager
def print_run_time(message: str | list) -> Generator[None, None, None]:
    start_time = time.perf_counter()
    try:
        yield
    finally:
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time

        # support message by reference
        if isinstance(message, list):
            message = message[0]

        print(f'[⏱️] {message} took {elapsed_time:.3f}s')


def get_http_client(base_url: str = '', *, auth: tuple | None = None, headers: dict | None = None) -> httpx.AsyncClient:
    if not headers:
        headers = {}

    headers['User-Agent'] = USER_AGENT

    return httpx.AsyncClient(
        base_url=base_url,
        follow_redirects=True,
        timeout=30,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=2, keepalive_expiry=30),
        http2=True,
        auth=auth,
        headers=headers)


def ensure_list(obj: dict | list[dict]) -> list[dict]:
    if isinstance(obj, list):
        return obj
    else:
        return [obj]


@njit(fastmath=True)
def radians_tuple(latLng: tuple[float, float]) -> tuple[float, float]:
    return (radians(latLng[0]), radians(latLng[1]))


EARTH_RADIUS = 6371000


@njit(fastmath=True)
def haversine_distance(latLng1: tuple[float, float], latLng2: tuple[float, float], unit_radians: bool = False) -> float:
    if unit_radians:
        lat1_rad, lon1_rad = latLng1
        lat2_rad, lon2_rad = latLng2
    else:
        lat1_rad, lon1_rad = radians_tuple(latLng1)
        lat2_rad, lon2_rad = radians_tuple(latLng2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    # distance in meters
    return c * EARTH_RADIUS
