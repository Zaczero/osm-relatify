from typing import NamedTuple


class ElementId(str):
    def __new__(cls, value: int | str, *, extraNum: int | None = None, maxNum: int | None = None):
        assert (extraNum is None) == (maxNum is None)

        if extraNum is None:
            return super().__new__(cls, str(value))
        else:
            assert 1 <= extraNum <= maxNum
            return super().__new__(cls, '_'.join((
                str(value),
                str(extraNum),
                str(maxNum)
            )))


class ElementIdParts(NamedTuple):
    id: int
    extraNum: int | None
    maxNum: int | None


def split_element_id(elementId: ElementId) -> ElementIdParts:
    split = elementId.split('_')

    if len(split) == 1:
        return ElementIdParts(*map(int, split), None, None)
    else:
        return ElementIdParts(*map(int, split))
