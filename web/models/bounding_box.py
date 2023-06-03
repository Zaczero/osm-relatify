from dataclasses import dataclass
from math import cos, degrees, radians
from typing import Self

from config import DOWNLOAD_RELATION_GRID_SIZE


@dataclass(frozen=True, kw_only=True, slots=True)
class BoundingBox:
    minlat: float
    minlon: float
    maxlat: float
    maxlon: float

    def __str__(self) -> str:
        return f'{self.minlat:.6f},{self.minlon:.6f},{self.maxlat:.6f},{self.maxlon:.6f}'

    def extend(self, unit_meters: float = None, *, unit_degrees: float = None) -> Self:
        if unit_meters is not None:
            earth_radius = 6371000  # Earth's radius in meters
            lat_delta = degrees(unit_meters / earth_radius)
            lng_delta = degrees(unit_meters / (earth_radius * cos(radians(self.minlat))))
        elif unit_degrees is not None:
            lat_delta = unit_degrees
            lng_delta = unit_degrees
        else:
            raise ValueError('Either unit_meters or unit_degrees must be specified')

        return BoundingBox(
            minlat=self.minlat - lat_delta,
            minlon=self.minlon - lng_delta,
            maxlat=self.maxlat + lat_delta,
            maxlon=self.maxlon + lng_delta,
        )

    def get_grid_cells(self) -> set[tuple[int, int]]:
        min_x, min_y = self.to_grid_cell()
        max_x, max_y = BoundingBox(
            minlat=self.maxlat,
            minlon=self.maxlon,
            maxlat=self.maxlat,
            maxlon=self.maxlon).to_grid_cell()
        return {
            (x, y)
            for x in range(min_x, max_x + 1)
            for y in range(min_y, max_y + 1)}

    def to_grid_cell(self) -> tuple[int, int]:
        return (
            int(self.minlon // DOWNLOAD_RELATION_GRID_SIZE),
            int(self.minlat // DOWNLOAD_RELATION_GRID_SIZE))

    @classmethod
    def from_grid_cell(cls, x: int, y: int, x_max: int = None, y_max: int = None) -> Self:
        return BoundingBox(
            minlat=y * DOWNLOAD_RELATION_GRID_SIZE,
            minlon=x * DOWNLOAD_RELATION_GRID_SIZE,
            maxlat=((y_max or y) + 1) * DOWNLOAD_RELATION_GRID_SIZE,
            maxlon=((x_max or x) + 1) * DOWNLOAD_RELATION_GRID_SIZE)
