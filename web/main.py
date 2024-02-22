import asyncio
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from itertools import chain

from authlib.integrations.httpx_client import AsyncOAuth2Client
from dacite import Config, from_dict
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from httpx import HTTPStatusError
from msgspec.json import Decoder, Encoder
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.websockets import WebSocketState

from compression import deflate_compress, deflate_decompress
from config import (
    CALC_ROUTE_MAX_PROCESSES,
    CALC_ROUTE_N_PROCESSES,
    CREATED_BY,
    OSM_CLIENT,
    OSM_SCOPES,
    OSM_SECRET,
    SECRET,
    USER_AGENT,
    WEBSITE,
)
from cython_lib.route import calc_bus_route
from deflate_middleware import DeflateRoute
from models.download_history import Cell, DownloadHistory
from models.element_id import ElementId
from models.fetch_relation import (
    FetchRelation,
    FetchRelationBusStopCollection,
    FetchRelationElement,
    PublicTransport,
    assign_none_members,
    find_start_stop_ways,
)
from models.final_route import FinalRoute, WarningSeverity
from openstreetmap import OpenStreetMap
from overpass import Overpass
from relation_builder import build_osm_change, get_relation_members, sort_and_upgrade_members
from route_warnings import check_for_issues
from user_session import fetch_user_details, require_user_details, require_user_token, set_user_token, unset_user_token
from utils import print_run_time

INDEX_REDIRECT = RedirectResponse('/', status_code=status.HTTP_302_FOUND)

_json_decode = Decoder().decode
_json_encode = Encoder(decimal_format='number').encode

app = FastAPI()
app.router.route_class = DeflateRoute
app.add_middleware(SessionMiddleware, secret_key=SECRET, max_age=31536000)  # 1 year
app.mount('/static', StaticFiles(directory='static', html=True), name='static')

templates = Jinja2Templates(directory='templates')

process_executor = ProcessPoolExecutor(CALC_ROUTE_MAX_PROCESSES)
openstreetmap = OpenStreetMap()
overpass = Overpass()


@app.get('/')
async def index(request: Request, user=Depends(fetch_user_details)):
    if user is not None:
        return templates.TemplateResponse('authorized.jinja2', {'request': request, 'user': user})
    else:
        return templates.TemplateResponse('index.jinja2', {'request': request})


@app.post('/login')
async def login(request: Request):
    async with AsyncOAuth2Client(
        client_id=OSM_CLIENT,
        scope=OSM_SCOPES,
        redirect_uri=str(request.url_for('callback')),
    ) as oauth:
        authorization_url, state = oauth.create_authorization_url('https://www.openstreetmap.org/oauth2/authorize')

    request.session['oauth_state'] = state
    return RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get('/callback')
async def callback(request: Request):
    state = request.session.pop('oauth_state', None)

    if state is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Invalid OAuth state')

    async with AsyncOAuth2Client(
        client_id=OSM_CLIENT,
        client_secret=OSM_SECRET,
        redirect_uri=str(request.url_for('callback')),
        state=state,
        headers={'User-Agent': USER_AGENT},
    ) as oauth:
        token = await oauth.fetch_token(
            'https://www.openstreetmap.org/oauth2/token',
            authorization_response=str(request.url),
        )

    set_user_token(request, token)
    return INDEX_REDIRECT


@app.post('/logout')
def logout(_=Depends(unset_user_token)):
    return INDEX_REDIRECT


def get_route_type(tags: dict[str, str]) -> str | None:
    if tags.get('public_transport:version') != '2':
        return None

    type = tags.get('type')

    if type not in ('route', 'disused:route', 'was:route'):
        return None

    type_specifier = tags.get(type)

    if type_specifier not in ('bus',):
        return None

    return type_specifier


class PostQueryModel(BaseModel):
    relationId: int
    downloadHistory: dict | None = None
    downloadTargets: tuple[dict, ...] | None = None
    reload: bool = False


@app.post('/query')
async def post_query(model: PostQueryModel, _=Depends(require_user_details)):
    print(f'🔍 Querying relation ({model.relationId})')
    assert (model.downloadHistory is None) == (model.downloadTargets is None)

    if model.downloadHistory is not None:
        download_hist = from_dict(DownloadHistory, model.downloadHistory, Config(cast=[tuple], strict=True))
        download_targets = tuple(from_dict(Cell, t, Config(cast=[], strict=True)) for t in model.downloadTargets)

        if model.reload:
            download_hist = replace(
                download_hist,
                session=DownloadHistory.make_session(),
                history=(tuple(chain.from_iterable(download_hist.history)),),
            )
    else:
        download_hist = None
        download_targets = None

    with print_run_time('Querying relation data'):
        query_task = asyncio.create_task(overpass.query_relation(model.relationId, download_hist, download_targets))
        get_task = asyncio.create_task(openstreetmap.get_relation(model.relationId))

        try:
            relation = await get_task
        except HTTPStatusError as e:
            query_task.cancel()
            if e.response.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(status.HTTP_404_NOT_FOUND, 'Relation not found') from e
            raise

        relation_tags = relation.get('tags', {})

        if get_route_type(relation_tags) is None:
            query_task.cancel()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Relation must be a PTv2 bus route')

        bounds, download_hist, download_triggers, ways, id_map, bus_stop_collections = await query_task

    with print_run_time('Finding start/stop ways'):
        start_way, stop_way = find_start_stop_ways(ways, id_map, relation)

    with print_run_time('Assigning members for bus stops'):
        bus_stop_collections = assign_none_members(bus_stop_collections, relation)

    return FetchRelation(
        fetchMerge=len(download_hist.history) > 1 or model.reload,
        nameOrRef=relation_tags.get('name', relation_tags.get('ref', '')).strip(),
        bounds=bounds,
        downloadHistory=download_hist,
        downloadTriggers=download_triggers,
        tags=relation['tags'],
        startWay=start_way,
        stopWay=stop_way,
        ways=ways,
        busStops=bus_stop_collections,
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class PostCalcBusRouteModel:
    relationId: int
    startWay: ElementId
    stopWay: ElementId
    ways: dict[ElementId | str, FetchRelationElement]
    busStops: list[FetchRelationBusStopCollection]
    tags: dict[str, str]


@app.websocket('/ws/calc_bus_route')
async def post_calc_bus_route(ws: WebSocket, _=Depends(require_user_details)):
    await ws.accept()

    try:
        while True:
            body = await ws.receive_bytes()
            body = deflate_decompress(body)
            json: dict = _json_decode(body)
            model = from_dict(
                PostCalcBusRouteModel,
                json,
                Config(cast=[ElementId, tuple, PublicTransport], strict=True),
            )

            print(f'🛣️ Calculating bus route ({model.relationId})')
            assert model.startWay in model.ways, 'Start way not in ways'
            assert model.stopWay in model.ways, 'Stop way not in ways'
            assert all(way_id == way.id for way_id, way in model.ways.items()), 'Way ids must match'

            ways_members = {way_id: way for way_id, way in model.ways.items() if way.member}
            ways_non_members = {way_id: way for way_id, way in model.ways.items() if not way.member}

            assert ways_members, 'No ways are members of the relation'

            assert all(
                collection.platform.member for collection in model.busStops if collection.platform
            ), 'All bus platforms must be members of the relation'
            assert all(
                collection.stop.member for collection in model.busStops if collection.stop
            ), 'All bus stops must be members of the relation'

            try:
                async with asyncio.TaskGroup() as tg:
                    get_task = tg.create_task(openstreetmap.get_relation(model.relationId))
                    route_task = tg.create_task(
                        asyncio.wait_for(
                            calc_bus_route(
                                ways_members,
                                model.startWay,
                                model.stopWay,
                                model.busStops,
                                model.tags,
                                process_executor,
                                n_processes=CALC_ROUTE_N_PROCESSES,
                            ),
                            timeout=3,
                        )
                    )

            except asyncio.TimeoutError as e:
                raise HTTPException(status.HTTP_408_REQUEST_TIMEOUT, 'Route calculation timed out') from e

            relation = get_task.result()
            relation_members = get_relation_members(relation)

            route = route_task.result()
            route = replace(route, extraWaysToUpdate=tuple(ways_non_members.values()))
            route = sort_and_upgrade_members(route, relation_members)

            final_route = check_for_issues(
                route=route,
                ways=ways_members,
                start_way=model.startWay,
                end_way=model.stopWay,
                bus_stop_collections=model.busStops,
                relation_members=relation_members,
            )

            body = _json_encode(final_route)
            body = deflate_compress(body)
            await ws.send_bytes(body)
    except WebSocketDisconnect:
        pass
    finally:
        if ws.client_state == WebSocketState.CONNECTED and ws.application_state == WebSocketState.CONNECTED:
            await ws.close(1011)


class PostDownloadOsmChangeModel(BaseModel):
    relationId: int
    route: dict
    tags: dict[str, str]

    def make_comment(self) -> str:
        tags_name = self.tags.get('name', '')
        tags_ref = self.tags.get('ref', '')

        # only include ref if it's not already in the name
        if tags_ref and tags_ref in tags_name:
            tags_ref = None

        if tags_name and tags_ref:
            return f'Updated bus route: {tags_ref} {tags_name}, #{self.relationId}'
        elif tags_name:
            return f'Updated bus route: {tags_name}, #{self.relationId}'
        elif tags_ref:
            return f'Updated bus route: {tags_ref}, #{self.relationId}'
        else:
            return f'Updated bus route #{self.relationId}'


@app.post('/download_osm_change')
async def post_download_osm_change(model: PostDownloadOsmChangeModel, _=Depends(require_user_details)):
    print(f'💾 Downloading OSM change ({model.relationId})')

    route = from_dict(
        FinalRoute,
        model.route,
        Config(cast=[ElementId, tuple, PublicTransport, WarningSeverity], strict=True),
    )

    with print_run_time('Building OSM change'):
        osm_change = await build_osm_change(
            model.relationId,
            route,
            include_changeset_id=False,
            overpass=overpass,
            osm=openstreetmap,
        )

    return Response(content=osm_change, media_type='text/xml; charset=utf-8')


@app.post('/upload_osm')
async def post_upload_osm(model: PostDownloadOsmChangeModel, token=Depends(require_user_token)):
    print(f'🌐 Uploading OSM change ({model.relationId})')

    route = from_dict(
        FinalRoute,
        model.route,
        Config(cast=[ElementId, tuple, PublicTransport, WarningSeverity], strict=True),
    )

    with print_run_time('Building OSM change'):
        osm_change = await build_osm_change(
            model.relationId,
            route,
            include_changeset_id=True,
            overpass=overpass,
            osm=openstreetmap,
        )

    openstreetmap_auth = OpenStreetMap(oauth_token=token)
    openstreetmap_user = await openstreetmap_auth.get_authorized_user()
    user_edits = openstreetmap_user['changesets']['count']

    upload_result = await openstreetmap_auth.upload_osm_change(
        osm_change,
        {
            'changesets_count': user_edits + 1,
            'comment': model.make_comment(),
            'created_by': CREATED_BY,
            'website': WEBSITE,
        },
    )

    if upload_result.ok:
        print(f'✅ Changeset upload success: #{upload_result.changeset_id}')
    else:
        print(f'🚩 Changeset upload failure: {upload_result}')

    return upload_result
