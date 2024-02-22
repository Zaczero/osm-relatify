from typing import NamedTuple, TypeAlias

ElementId: TypeAlias = str


class ElementIdParts(NamedTuple):
    id: int
    extra_num: int | None
    max_num: int | None


def element_id(value: int | str, *, extra_num: int | None = None, max_num: int | None = None) -> ElementId:
    assert (extra_num is None) == (max_num is None)

    if extra_num is None:
        return ElementId(value)
    else:
        assert 1 <= extra_num <= max_num
        return ElementId(f'{value}_{extra_num}_{max_num}')


def split_element_id(element_id: ElementId) -> ElementIdParts:
    split = element_id.split('_')

    if len(split) == 1:
        return ElementIdParts(int(split[0]), None, None)
    else:
        return ElementIdParts(*map(int, split))
