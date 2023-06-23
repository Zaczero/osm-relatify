import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pprint import pprint
from typing import Optional

import orjson
from authlib.integrations.starlette_client import OAuth
from cachetools import TTLCache
from dacite import Config, from_dict
from fastapi import (Depends, FastAPI, HTTPException, Request, Response,
                     WebSocket, WebSocketDisconnect, status)
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from httpx import HTTPStatusError
from itsdangerous import Serializer
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.websockets import WebSocketState
from tenacity import retry, stop_after_attempt, wait_exponential

from compression import deflate_compress, deflate_decompress
from config import (CALC_ROUTE_MAX_PROCESSES, CALC_ROUTE_N_PROCESSES,
                    CREATED_BY, SECRET, WEBSITE)
from deflate_middleware import DeflateRoute
from models.download_history import Cell, DownloadHistory
from models.element_id import ElementId
from models.fetch_relation import (FetchRelation,
                                   FetchRelationBusStopCollection,
                                   FetchRelationElement, PublicTransport,
                                   assign_none_members, find_start_stop_ways)
from models.final_route import FinalRoute, WarningSeverity
from openstreetmap import OpenStreetMap, UploadResult
from orjson_response import ORJSONResponse
from overpass import Overpass
from relation_builder import (build_osm_change, get_relation_members,
                              sort_and_upgrade_members)
from route import calc_bus_route
from route_warnings import check_for_issues
from utils import print_run_time

oauth = OAuth()
oauth.register(
    name='osm',
    client_id=os.getenv('CONSUMER_KEY'),
    client_secret=os.getenv('CONSUMER_SECRET'),
    request_token_url='https://www.openstreetmap.org/oauth/request_token',
    access_token_url='https://www.openstreetmap.org/oauth/access_token',
    authorize_url='https://www.openstreetmap.org/oauth/authorize')

app = FastAPI(default_response_class=ORJSONResponse)
app.add_middleware(SessionMiddleware, secret_key=SECRET)
app.router.route_class = DeflateRoute
app.mount('/static', StaticFiles(directory='static', html=True), name='static')

secret = Serializer(SECRET)
templates = Jinja2Templates(directory='templates')

user_details_cache = TTLCache(maxsize=1024, ttl=3600)  # 1 hour cache

process_executor = ProcessPoolExecutor(CALC_ROUTE_MAX_PROCESSES)
openstreetmap = OpenStreetMap()
overpass = Overpass()


@retry(wait=wait_exponential(), stop=stop_after_attempt(3))
async def fetch_user_details(request: Request = None, websocket: WebSocket = None) -> Optional[dict]:
    if request is not None:
        cookies = request.cookies
    elif websocket is not None:
        cookies = websocket.cookies
    else:
        raise ValueError('Either request or websocket must be provided')

    if 'token' not in cookies:
        return None

    try:
        token = secret.loads(cookies['token'])
    except Exception:
        return None

    user_cache_key = token['oauth_token_secret']

    try:
        return user_details_cache[user_cache_key]
    except Exception:
        response = await oauth.osm.get('https://api.openstreetmap.org/api/0.6/user/details.json', token=token)

        if response.status_code != 200:
            return None

        try:
            user = response.json()['user']
        except Exception:
            return None

        if 'img' not in user:
            user['img'] = {'href': None}

        user_details_cache[user_cache_key] = user
        return user


async def require_user_details(user=Depends(fetch_user_details)) -> dict:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return user


@app.get('/')
@app.post('/')
async def index(request: Request, user=Depends(fetch_user_details)):
    if user is not None:
        return templates.TemplateResponse('authorized.jinja2', {'request': request, 'user': user})
    else:
        return templates.TemplateResponse('index.jinja2', {'request': request})


@app.post('/login')
async def login(request: Request):
    return await oauth.osm.authorize_redirect(request, str(request.url_for('callback')))


@app.get('/callback')
async def callback(request: Request):
    token = await oauth.osm.authorize_access_token(request)

    response = RedirectResponse(request.url_for('index'))
    response.set_cookie('token', secret.dumps(token),
                        max_age=(365 * 24 * 3600),
                        secure=request.url.scheme == 'https',
                        httponly=True)

    return response


@app.post('/logout')
async def logout(request: Request):
    response = RedirectResponse(request.url_for('index'))
    response.set_cookie('token', '', max_age=0)

    return response


class PostQueryModel(BaseModel):
    relationId: int
    downloadHistory: dict | None = None
    downloadTargets: tuple[dict, ...] | None = None


@app.post('/query')
async def post_query(model: PostQueryModel, user: dict = Depends(require_user_details)) -> FetchRelation:
    print(f'🔍 Querying relation ({model.relationId})')
    assert (model.downloadHistory is None) == (model.downloadTargets is None)

    if model.downloadHistory is not None:
        download_hist = from_dict(DownloadHistory, model.downloadHistory, Config(cast=[tuple], strict=True))
        download_targets = tuple(from_dict(Cell, t, Config(cast=[], strict=True)) for t in model.downloadTargets)
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
                raise HTTPException(status.HTTP_404_NOT_FOUND, 'Relation not found')
            raise

        relation_tags = relation.get('tags', {})

        if relation_tags.get('type') != 'route' or \
                relation_tags.get('route') != 'bus' or \
                relation_tags.get('public_transport:version') != '2':
            query_task.cancel()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Relation must be a PTv2 bus route')

        bounds, download_hist, download_triggers, ways, id_map, bus_stop_collections = await query_task

    with print_run_time('Finding start/stop ways'):
        start_way, stop_way = find_start_stop_ways(ways, id_map, relation)

    with print_run_time('Assigning members for bus stops'):
        bus_stop_collections = assign_none_members(bus_stop_collections, relation)

    return FetchRelation(
        fetchMerge=len(download_hist.history) > 1,
        nameOrRef=relation_tags.get('name', relation_tags.get('ref', '')).strip(),
        bounds=bounds,
        downloadHistory=download_hist,
        downloadTriggers=download_triggers,
        tags=relation['tags'],
        startWay=start_way,
        stopWay=stop_way,
        ways=ways,
        busStops=bus_stop_collections)


@dataclass(frozen=True, kw_only=True, slots=True)
class PostCalcBusRouteModel:
    relationId: int
    startWay: ElementId
    stopWay: ElementId
    ways: dict[ElementId | str, FetchRelationElement]
    busStops: list[FetchRelationBusStopCollection]


@app.websocket('/ws/calc_bus_route')
async def post_calc_bus_route(ws: WebSocket, user: dict = Depends(require_user_details)):
    await ws.accept()

    try:
        while True:
            body = await ws.receive_bytes()
            body = deflate_decompress(body)
            json = orjson.loads(body)
            model = from_dict(PostCalcBusRouteModel, json,
                              Config(cast=[ElementId, tuple, PublicTransport], strict=True))

            print(f'🛣️ Calculating bus route ({model.relationId})')
            assert model.startWay in model.ways, 'Start way not in ways'
            assert model.stopWay in model.ways, 'Stop way not in ways'
            assert all(way_id == way.id for way_id, way in model.ways.items()), 'Way ids must match'

            ways_members = {
                way_id: way
                for way_id, way in model.ways.items()
                if way.member}

            ways_non_members = {
                way_id: way
                for way_id, way in model.ways.items()
                if not way.member}

            assert ways_members, 'No ways are members of the relation'

            assert all(collection.platform.member
                       for collection in model.busStops
                       if collection.platform), 'All bus platforms must be members of the relation'
            assert all(collection.stop.member
                       for collection in model.busStops
                       if collection.stop), 'All bus stops must be members of the relation'

            try:
                async with asyncio.TaskGroup() as tg:
                    get_task = tg.create_task(openstreetmap.get_relation(model.relationId))
                    route_task = tg.create_task(asyncio.wait_for(
                        calc_bus_route(
                            ways_members,
                            model.startWay,
                            model.stopWay,
                            model.busStops,
                            process_executor,
                            n_processes=CALC_ROUTE_N_PROCESSES),
                        timeout=3))

            except asyncio.TimeoutError:
                raise HTTPException(status.HTTP_408_REQUEST_TIMEOUT, 'Route calculation timed out')

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
                relation_members=relation_members)

            body = orjson.dumps(final_route, option=orjson.OPT_NON_STR_KEYS)
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


@app.post('/download_osm_change')
async def post_download_osm_change(model: PostDownloadOsmChangeModel, user=Depends(require_user_details)):
    print(f'💾 Downloading OSM change ({model.relationId})')

    route = from_dict(FinalRoute, model.route,
                      Config(cast=[ElementId, tuple, PublicTransport, WarningSeverity], strict=True))

    with print_run_time('Building OSM change'):
        osm_change = await build_osm_change(model.relationId, route, include_changeset_id=False, overpass=overpass, osm=openstreetmap)

    return Response(content=osm_change, media_type='text/xml; charset=utf-8')


@app.post('/upload_osm')
async def post_upload_osm(request: Request, model: PostDownloadOsmChangeModel, user=Depends(require_user_details)) -> UploadResult:
    print(f'🌐 Uploading OSM change ({model.relationId})')

    route = from_dict(FinalRoute, model.route,
                      Config(cast=[ElementId, tuple, PublicTransport, WarningSeverity], strict=True))

    with print_run_time('Building OSM change'):
        osm_change = await build_osm_change(model.relationId, route, include_changeset_id=True, overpass=overpass, osm=openstreetmap)

    token = secret.loads(request.cookies['token'])
    oauth_token = token['oauth_token']
    oauth_token_secret = token['oauth_token_secret']

    openstreetmap_auth = OpenStreetMap(oauth_token=oauth_token, oauth_token_secret=oauth_token_secret)
    openstreetmap_user = await openstreetmap_auth.get_authorized_user()
    user_edits = openstreetmap_user['changesets']['count']

    upload_result = await openstreetmap_auth.upload_osm_change(osm_change, {
        'changesets_count': user_edits + 1,
        'comment': f'Updated bus route #{model.relationId}',
        'created_by': CREATED_BY,
        'website': WEBSITE,
    })

    if upload_result.ok:
        print(f'✅ Changeset upload success: #{upload_result.changeset_id}')
    else:
        print(f'🚩 Changeset upload failure: {upload_result}')

    return upload_result
