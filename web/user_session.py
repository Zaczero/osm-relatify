from authlib.integrations.httpx_client import OAuth2Auth
from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request, status
from fastapi.websockets import WebSocket
from tenacity import retry, stop_after_attempt, wait_exponential

from utils import get_http_client

_user_cache = TTLCache(maxsize=1024, ttl=7200)  # 2 hours


@retry(wait=wait_exponential(), stop=stop_after_attempt(3), reraise=True)
async def fetch_user_details(request: Request = None, websocket: WebSocket = None) -> dict | None:
    if request is not None:
        session = request.session
    elif websocket is not None:
        session = websocket.session
    else:
        raise ValueError('Either request or websocket must be provided')

    try:
        token = session['token']
    except KeyError:
        return None

    cache_key = token['access_token']

    try:
        return _user_cache[cache_key]
    except KeyError:
        pass

    async with get_http_client('https://api.openstreetmap.org/api', auth=OAuth2Auth(token)) as http:
        response = await http.get('/0.6/user/details.json')

    if not response.is_success:
        return None

    try:
        user = response.json()['user']
    except Exception:
        return None

    if 'img' not in user:
        user['img'] = {'href': None}

    _user_cache[cache_key] = user
    return user


async def require_user_details(user=Depends(fetch_user_details)) -> dict:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')
    return user


def require_user_token(request: Request) -> dict:
    try:
        return request.session['token']
    except KeyError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')


def set_user_token(request: Request, token: dict) -> bool:
    request.session['token'] = token
    return True


def unset_user_token(request: Request) -> bool:
    try:
        del request.session['token']
        return True
    except KeyError:
        return False
