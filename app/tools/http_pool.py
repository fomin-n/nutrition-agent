import atexit
from functools import lru_cache

import httpx


@lru_cache(maxsize=1)
def provider_http_client() -> httpx.Client:
    client = httpx.Client(
        timeout=8.0,
        limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
    )
    atexit.register(client.close)
    return client
