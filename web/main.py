import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from typing import Optional

from authlib.integrations.starlette_client import OAuth
from cachetools import TTLCache
from dacite import Config, from_dict
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import Serializer
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from tenacity import retry, stop_after_attempt, wait_exponential

from config import (CALC_ROUTE_MAX_PROCESSES, CALC_ROUTE_N_PROCESSES,
                    CREATED_BY, SECRET, WEBSITE)
from models.element_id import ElementId
from models.fetch_relation import (FetchRelation,
                                   FetchRelationBusStopCollection,
                                   FetchRelationElement, PublicTransport,
                                   assign_none_members, find_start_stop_ways)
from models.final_route import FinalRoute
from openstreetmap import OpenStreetMap, UploadResult
from overpass import Overpass
from relation_builder import (build_osm_change, get_relation_members,
                              sort_and_upgrade_members)
from route import calc_bus_route
from route_warnings import check_for_issues

oauth = OAuth()
oauth.register(
    name='osm',
    client_id=os.getenv('CONSUMER_KEY'),
    client_secret=os.getenv('CONSUMER_SECRET'),
    request_token_url='https://www.openstreetmap.org/oauth/request_token',
    access_token_url='https://www.openstreetmap.org/oauth/access_token',
    authorize_url='https://www.openstreetmap.org/oauth/authorize'
)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET)
app.mount('/static', StaticFiles(directory='static', html=True), name='static')

secret = Serializer(SECRET)
templates = Jinja2Templates(directory='templates')

user_details_cache = TTLCache(maxsize=1024, ttl=3600)  # 1 hour cache

process_executor = ProcessPoolExecutor(CALC_ROUTE_MAX_PROCESSES)
openstreetmap = OpenStreetMap()
overpass = Overpass()


@retry(wait=wait_exponential(), stop=stop_after_attempt(3))
async def fetch_user_details(request: Request) -> Optional[dict]:
    if 'token' not in request.cookies:
        return None

    try:
        token = secret.loads(request.cookies['token'])
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


@app.get('/')
@app.post('/')
async def index(request: Request):
    if user := await fetch_user_details(request):
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


@app.post('/query')
async def post_query(model: PostQueryModel) -> FetchRelation:
    async with asyncio.TaskGroup() as tg:
        query_task = tg.create_task(overpass.query_relation(model.relationId))
        get_task = tg.create_task(openstreetmap.get_relation(model.relationId))

    bounds, ways, id_map, bus_stop_collections = query_task.result()
    relation = get_task.result()
    relation_tags = relation.get('tags', {})

    if relation_tags.get('type') != 'route' or \
            relation_tags.get('route') != 'bus' or \
            relation_tags.get('public_transport:version') != '2':
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Relation must be a PTv2 bus route')

    start_way, stop_way = find_start_stop_ways(ways, id_map, relation)
    bus_stop_collections = assign_none_members(bus_stop_collections, relation)

    return FetchRelation(
        nameOrRef=relation_tags.get('name', relation_tags.get('ref', '')).strip(),
        bounds=bounds,
        tags=relation['tags'],
        startWay=start_way,
        stopWay=stop_way,
        ways=ways,
        busStops=bus_stop_collections)


class PostCalcBusRouteModel(BaseModel):
    relationId: int
    startWay: ElementId
    stopWay: ElementId
    ways: dict[ElementId, dict]
    busStops: list[dict]


@app.post('/calc_bus_route')
async def post_calc_bus_route(model: PostCalcBusRouteModel) -> FinalRoute:
    # TODO: caching?

    assert model.startWay in model.ways, 'Start way not in ways'
    assert model.stopWay in model.ways, 'Stop way not in ways'

    ways = {
        ElementId(way_id): from_dict(FetchRelationElement, way, Config(cast=[ElementId, tuple], strict=True))
        for way_id, way in model.ways.items()}

    assert all(way_id == way.id for way_id, way in ways.items()), 'Way ids must match'

    ways_members = {
        way_id: way
        for way_id, way in ways.items()
        if way.member}

    ways_non_members = {
        way_id: way
        for way_id, way in ways.items()
        if not way.member}

    assert ways_members, 'No ways are members of the relation'

    bus_stop_collections = [
        from_dict(FetchRelationBusStopCollection, bus_stop,
                  Config(cast=[ElementId, tuple, PublicTransport], strict=True))
        for bus_stop in model.busStops]

    assert all(collection.platform.member for collection in bus_stop_collections if collection.platform), 'All bus platforms must be members of the relation'
    assert all(collection.stop.member for collection in bus_stop_collections if collection.stop), 'All bus stops must be members of the relation'

    try:
        async with asyncio.TaskGroup() as tg:
            get_task = tg.create_task(openstreetmap.get_relation(model.relationId))
            route_task = tg.create_task(asyncio.wait_for(
                calc_bus_route(
                    ways_members,
                    model.startWay,
                    model.stopWay,
                    bus_stop_collections,
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

    return check_for_issues(route, ways_members, model.startWay, model.stopWay, bus_stop_collections, relation_members)


class PostDownloadOsmChangeModel(BaseModel):
    relationId: int
    route: dict


@app.post('/download_osm_change')
async def post_download_osm_change(model: PostDownloadOsmChangeModel):
    route = from_dict(FinalRoute, model.route, Config(cast=[ElementId, tuple, PublicTransport], strict=True))

    osm_change = await build_osm_change(model.relationId, route, include_changeset_id=False, overpass=overpass, osm=openstreetmap)

    return Response(content=osm_change, media_type='text/xml; charset=utf-8')


@app.post('/upload_osm')
async def post_upload_osm(request: Request, model: PostDownloadOsmChangeModel) -> UploadResult:
    token = secret.loads(request.cookies['token'])
    oauth_token = token['oauth_token']
    oauth_token_secret = token['oauth_token_secret']

    openstreetmap_auth = OpenStreetMap(oauth_token=oauth_token, oauth_token_secret=oauth_token_secret)
    openstreetmap_user = await openstreetmap_auth.get_authorized_user()
    user_edits = openstreetmap_user['changesets']['count']

    route = from_dict(FinalRoute, model.route, Config(cast=[ElementId, tuple, PublicTransport], strict=True))

    osm_change = await build_osm_change(model.relationId, route, include_changeset_id=True, overpass=overpass, osm=openstreetmap)

    upload_result = await openstreetmap_auth.upload_osm_change(osm_change, {
        'changesets_count': user_edits + 1,
        'comment': f'Updated bus route #{model.relationId}',
        'created_by': CREATED_BY,
        'website': WEBSITE,
    })

    return upload_result
