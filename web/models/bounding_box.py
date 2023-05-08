from dataclasses import dataclass
from math import cos, degrees, radians
from typing import Self


@dataclass(frozen=True, kw_only=True, slots=True)
class BoundingBox:
    minlat: float
    minlon: float
    maxlat: float
    maxlon: float

    def extend(self, meters: float) -> Self:
        earth_radius = 6371000  # Earth's radius in meters
        lat_delta = degrees(meters / earth_radius)
        lng_delta = degrees(meters / (earth_radius * cos(radians(self.minlat))))

        return BoundingBox(
            minlat=self.minlat - lat_delta,
            minlon=self.minlon - lng_delta,
            maxlat=self.maxlat + lat_delta,
            maxlon=self.maxlon + lng_delta,
        )
