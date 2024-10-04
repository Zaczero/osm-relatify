from collections.abc import Iterable
from dataclasses import dataclass

import httpx
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
        self.headers = {'Authorization': f'Bearer {access_token}'} if access_token else {}

    def _get_http_client(self) -> httpx.AsyncClient:
        return get_http_client('https://api.openstreetmap.org/api', headers=self.headers)

    async def get_changeset_maxsize(self) -> int:
        async with self._get_http_client() as http:
            r = await http.get('/capabilities')
            r.raise_for_status()

        caps = xmltodict.parse(r.text)

        return int(caps['osm']['api']['changesets']['@maximum_elements'])

    async def get_relation(self, relation_id: str | int, *, json: bool = True) -> dict:
        return (await self._get_elements('relations', (relation_id,), json=json))[0]

    async def get_way(self, way_id: str | int, *, json: bool = True) -> dict:
        return (await self._get_elements('ways', (way_id,), json=json))[0]

    async def get_node(self, node_id: str | int, *, json: bool = True) -> dict:
        return (await self._get_elements('nodes', (node_id,), json=json))[0]

    async def get_relations(self, relation_ids: list[str | int], *, json: bool = True) -> list[dict]:
        return await self._get_elements('relations', relation_ids, json=json)

    async def get_ways(self, way_ids: list[str | int], *, json: bool = True) -> list[dict]:
        return await self._get_elements('ways', way_ids, json=json)

    async def get_nodes(self, node_ids: list[str | int], *, json: bool = True) -> list[dict]:
        return await self._get_elements('nodes', node_ids, json=json)

    @cached(TTLCache(maxsize=1024, ttl=60))
    async def _get_elements(self, elements_type: str, element_ids: Iterable[str], json: bool) -> list[dict]:
        async with self._get_http_client() as http:
            r = await http.get(
                f'/0.6/{elements_type}{".json" if json else ""}',
                params={elements_type: ','.join(map(str, element_ids))},
            )
            r.raise_for_status()

        if json:
            return r.json()['elements']
        else:
            return ensure_list(xmltodict.parse(r.text)['osm'][elements_type[:-1]])

    async def get_authorized_user(self) -> dict:
        async with self._get_http_client() as http:
            r = await http.get('/0.6/user/details.json')
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

        changeset_dict = {
            'osm': {
                'changeset': {
                    'tag': [
                        {
                            '@k': k,
                            '@v': v,
                        }
                        for k, v in tags.items()
                    ]
                }
            }
        }

        changeset = xmltodict.unparse(changeset_dict)

        async with self._get_http_client() as http:
            r = await http.put(
                '/0.6/changeset/create',
                content=changeset,
                headers={'Content-Type': 'text/xml; charset=utf-8'},
                follow_redirects=False,
            )
            r.raise_for_status()

            changeset_id_raw = r.text
            changeset_id = int(changeset_id_raw)

            osm_change = osm_change.replace(CHANGESET_ID_PLACEHOLDER, changeset_id_raw)

            upload_resp = await http.post(
                f'/0.6/changeset/{changeset_id_raw}/upload',
                content=osm_change,
                headers={'Content-Type': 'text/xml; charset=utf-8'},
                timeout=150,
            )

            r = await http.put(f'/0.6/changeset/{changeset_id_raw}/close')
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
