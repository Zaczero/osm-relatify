import re
import time
from collections.abc import Generator
from contextlib import contextmanager

import httpx

from config import USER_AGENT


@contextmanager
def print_run_time(message: str | list) -> Generator[None, None, None]:
    start_time = time.monotonic()
    try:
        yield
    finally:
        end_time = time.monotonic()
        elapsed_time = end_time - start_time

        # support message by reference
        if isinstance(message, list):
            message = message[0]

        print(f'[⏱️] {message} took {elapsed_time:.3f}s')


def get_http_client(base_url: str = '', *, auth: tuple | None = None, headers: dict | None = None) -> httpx.AsyncClient:
    if not headers:
        headers = {}

    headers['User-Agent'] = USER_AGENT

    return httpx.AsyncClient(
        base_url=base_url,
        follow_redirects=True,
        http1=True,
        http2=True,
        timeout=30,
        auth=auth,
        headers=headers,
    )


def ensure_list(obj: dict | list[dict]) -> list[dict]:
    if isinstance(obj, list):
        return obj
    else:
        return [obj]


def normalize_name(
    name: str,
    *,
    lower: bool = False,
    number: bool = False,
    special: bool = False,
    whitespace: bool = False,
) -> str:
    if lower:
        name = name.lower()

    if number:
        name = re.sub(r'\b(\d\d)\b', r'0\1', name)
        name = re.sub(r'\b(\d)\b', r'00\1', name)

    if special:
        name = re.sub(r'[^\w\s]', '', name)

    if whitespace:
        name = re.sub(r'\s+', ' ', name).strip()

    return name


def extract_numbers(text: str) -> set[int]:
    return {int(n) for n in re.findall(r'\d+', text)}
