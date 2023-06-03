from rtree import index

from models.bounding_box import BoundingBox


class BoundingBoxCollection:
    def __init__(self, bbs: list[BoundingBox]):
        self.idx = index.Index()

        for i, bb in enumerate(bbs):
            self.idx.insert(i, (bb.minlon, bb.minlat, bb.maxlon, bb.maxlat))

    def contains(self, latLng: tuple[float, float]) -> bool:
        return bool(self.idx.contains((latLng[0], latLng[1], latLng[0], latLng[1])))
