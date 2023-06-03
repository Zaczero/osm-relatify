from typing import Any

import orjson
from fastapi import Response


class ORJSONResponse(Response):
    media_type = 'application/json'

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS)
