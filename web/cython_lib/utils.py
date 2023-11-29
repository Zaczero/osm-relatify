import cython

if cython.compiled:
    from cython.cimports.libc.math import atan2, cos, pi, sin, sqrt

    print('Cython: 🐇 compiled')
else:
    from math import atan2, cos, pi, sin, sqrt

    print('Cython: 🐌 not compiled')


@cython.cfunc
def _radians(x: cython.double) -> cython.double:
    return x * (pi / 180)


def radians_tuple(latlon: tuple[cython.double, cython.double]) -> tuple[cython.double, cython.double]:
    return _radians(latlon[0]), _radians(latlon[1])


def haversine_distance(
    latlon1: tuple[cython.double, cython.double],
    latlon2: tuple[cython.double, cython.double],
    unit_radians: bool = False,
) -> cython.double:
    if unit_radians:
        lat1_rad, lon1_rad = latlon1
        lat2_rad, lon2_rad = latlon2
    else:
        lat1_rad, lon1_rad = _radians(latlon1[0]), _radians(latlon1[1])
        lat2_rad, lon2_rad = _radians(latlon2[0]), _radians(latlon2[1])

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    R = 6_371_000  # earth radius

    # distance in meters
    return c * R
