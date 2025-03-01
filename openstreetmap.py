from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import xmltodict
from asyncache import cached
from cachetools import TTLCache

from config import CHANGESET_ID_PLACEHOLDER, TAG_MAX_LENGTH
from utils import ensure_list, get_http_client


@dataclass(frozen=True, kw_only=True, slots=True)
class UploadResult:
    ok: bool
    error_code: int | None
    error_message: str | None
    changeset_id: int | None


class OpenStreetMap:
    def __init__(self, *, access_token: str | None = None):
        self._http = get_http_client(
            'https://api.openstreetmap.org/api',
            headers={'Authorization': f'Bearer {access_token}'} if access_token else None,
        )

    async def __aenter__(self) -> 'OpenStreetMap':
        await self._http.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._http.__aexit__(exc_type, exc_val, exc_tb)

    async def get_changeset_maxsize(self) -> int:
        r = await self._http.get('/capabilities')
        r.raise_for_status()
        caps = xmltodict.parse(r.text)
        return int(caps['osm']['api']['changesets']['@maximum_elements'])

    async def get_relation(self, relation_id: str | int, *, json: bool = True) -> dict:
        return (await self._get_elements('relations', (relation_id,), json=json))[0]

    async def get_way(self, way_id: str | int, *, json: bool = True) -> dict:
        return (await self._get_elements('ways', (way_id,), json=json))[0]

    async def get_node(self, node_id: str | int, *, json: bool = True) -> dict:
        return (await self._get_elements('nodes', (node_id,), json=json))[0]

    async def get_relations(self, relation_ids: Iterable[str | int], *, json: bool = True) -> list[dict]:
        return await self._get_elements('relations', relation_ids, json=json)

    async def get_ways(self, way_ids: Iterable[str | int], *, json: bool = True) -> list[dict]:
        return await self._get_elements('ways', way_ids, json=json)

    async def get_nodes(self, node_ids: Iterable[str | int], *, json: bool = True) -> list[dict]:
        return await self._get_elements('nodes', node_ids, json=json)

    @cached(TTLCache(maxsize=1024, ttl=60))
    async def _get_elements(
        self,
        elements_type: Literal['nodes', 'ways', 'relations'],
        element_ids: Iterable[str | int],
        json: bool,
    ) -> list[dict]:
        r = await self._http.get(
            f'/0.6/{elements_type}{".json" if json else ""}',
            params={elements_type: ','.join(map(str, element_ids))},
        )
        r.raise_for_status()
        if json:
            return r.json()['elements']
        else:
            return ensure_list(xmltodict.parse(r.text)['osm'][elements_type[:-1]])

    async def get_authorized_user(self) -> dict:
        r = await self._http.get('/0.6/user/details.json')
        r.raise_for_status()
        return r.json()['user']

    async def upload_osm_change(self, osm_change: str, tags: dict[str, str]) -> UploadResult:
        assert 'comment' in tags, 'You must provide a comment'

        for key, value in tuple(tags.items()):
            # remove empty tags
            if not value:
                del tags[key]
                continue

            # stringify the value
            if not isinstance(value, str):
                value = str(value)
                tags[key] = value

            # trim value if too long
            if len(value) > TAG_MAX_LENGTH:
                print(f'🚧 Warning: Trimming {key} value because it exceeds {TAG_MAX_LENGTH} characters: {value}')
                tags[key] = value[: TAG_MAX_LENGTH - 1] + '…'

        changeset_dict = {'osm': {'changeset': {'tag': [{'@k': k, '@v': v} for k, v in tags.items()]}}}
        changeset = xmltodict.unparse(changeset_dict)

        r = await self._http.put(
            '/0.6/changeset/create',
            content=changeset,
            headers={'Content-Type': 'text/xml; charset=utf-8'},
            follow_redirects=False,
        )
        r.raise_for_status()
        changeset_id_raw = r.text
        changeset_id = int(changeset_id_raw)

        osm_change = osm_change.replace(CHANGESET_ID_PLACEHOLDER, changeset_id_raw)
        upload_resp = await self._http.post(
            f'/0.6/changeset/{changeset_id_raw}/upload',
            content=osm_change,
            headers={'Content-Type': 'text/xml; charset=utf-8'},
            timeout=150,
        )

        r = await self._http.put(f'/0.6/changeset/{changeset_id_raw}/close')
        r.raise_for_status()

        if not upload_resp.is_success:
            return UploadResult(
                ok=False,
                error_code=upload_resp.status_code,
                error_message=upload_resp.text,
                changeset_id=changeset_id,
            )

        return UploadResult(
            ok=True,
            error_code=None,
            error_message=None,
            changeset_id=changeset_id,
        )
