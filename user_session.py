from json import JSONDecodeError

from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request, status
from fastapi.websockets import WebSocket
from httpx import HTTPStatusError
from tenacity import retry, stop_after_attempt, wait_exponential

from openstreetmap import OpenStreetMap

_USER_CACHE = TTLCache(maxsize=1024, ttl=7200)  # 2 hours


@retry(wait=wait_exponential(), stop=stop_after_attempt(3), reraise=True)
async def fetch_user_details(
    request: Request = None,  # type: ignore
    websocket: WebSocket = None,  # type: ignore
) -> dict | None:
    if request is not None:
        cookies = request.cookies
    elif websocket is not None:
        cookies = websocket.cookies
    else:
        raise ValueError('Either request or websocket must be provided')

    access_token = cookies.get('access_token')
    if access_token is None:
        return None

    cached = _USER_CACHE.get(access_token)
    if cached is not None:
        return cached

    async with OpenStreetMap(access_token=access_token) as osm:
        try:
            user = await osm.get_authorized_user()
        except (HTTPStatusError, JSONDecodeError, KeyError):
            return None

    if 'img' not in user:
        user['img'] = {'href': None}

    _USER_CACHE[access_token] = user
    return user


async def require_user_details(user=Depends(fetch_user_details)) -> dict:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')
    return user


def require_user_access_token(request: Request) -> str:
    try:
        return request.cookies['access_token']
    except KeyError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Unauthorized') from e
