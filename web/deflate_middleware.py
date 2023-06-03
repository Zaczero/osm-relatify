import zlib
from typing import Callable

from fastapi import Request, Response
from fastapi.routing import APIRoute


class DeflateRequest(Request):
    async def body(self) -> bytes:
        if not hasattr(self, "_body"):
            body = await super().body()

            if self.headers.get('Content-Encoding') == 'deflate':
                body = zlib.decompress(body, -zlib.MAX_WBITS)

            self._body = body

        return self._body


class DeflateRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            request = DeflateRequest(request.scope, request.receive)
            return await original_route_handler(request)

        return custom_route_handler
