from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request, status
from fastapi.websockets import WebSocket
from tenacity import retry, stop_after_attempt, wait_exponential

from utils import get_http_client

_user_cache = TTLCache(maxsize=1024, ttl=7200)  # 2 hours


@retry(wait=wait_exponential(), stop=stop_after_attempt(3), reraise=True)
async def fetch_user_details(request: Request = None, websocket: WebSocket = None) -> dict | None:
    if request is not None:
        cookies = request.cookies
    elif websocket is not None:
        cookies = websocket.cookies
    else:
        raise ValueError('Either request or websocket must be provided')

    try:
        access_token = cookies['access_token']
    except KeyError:
        return None

    try:
        return _user_cache[access_token]
    except KeyError:
        pass

    async with get_http_client(
        'https://api.openstreetmap.org/api',
        headers={'Authorization': f'Bearer {access_token}'},
    ) as http:
        response = await http.get('/0.6/user/details.json')

    if not response.is_success:
        return None

    try:
        user = response.json()['user']
    except Exception:
        return None

    if 'img' not in user:
        user['img'] = {'href': None}

    _user_cache[access_token] = user
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
