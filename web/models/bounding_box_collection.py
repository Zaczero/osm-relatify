from rtree import index

from models.bounding_box import BoundingBox


class BoundingBoxCollection:
    def __init__(self, bbs: list[BoundingBox]):
        self.idx = index.Index()

        for i, bb in enumerate(bbs):
            self.idx.insert(i, (bb.minlat, bb.minlon, bb.maxlat, bb.maxlon))

    def contains(self, latLng: tuple[float, float]) -> bool:
        return bool(list(self.idx.intersection(latLng)))
