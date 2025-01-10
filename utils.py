import os
import re
import ssl
import time
from contextlib import contextmanager

from httpx import AsyncClient

from config import USER_AGENT

_SSL_CONTEXT = ssl.create_default_context(cafile=os.environ['SSL_CERT_FILE'])


def get_http_client(base_url: str = '', *, headers: dict | None = None) -> AsyncClient:
    if headers is None:
        headers = {}
    return AsyncClient(
        base_url=base_url,
        follow_redirects=True,
        timeout=30,
        headers={'User-Agent': USER_AGENT, **headers},
        verify=_SSL_CONTEXT,
    )


HTTP = get_http_client()


@contextmanager
def print_run_time(message: str | list):
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
