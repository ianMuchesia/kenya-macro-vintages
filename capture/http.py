"""The real fetch(url) used in production. Spec tests never import this module."""

import ssl
import time
from dataclasses import dataclass
from pathlib import Path

import certifi
import httpx

USER_AGENT = (
    "kenya-macro-vintages/0.1 "
    "(research; +https://github.com/ianMuchesia/kenya-macro-vintages)"
)
TIMEOUT_SECONDS = 30
RETRY_WAITS_SECONDS = (10, 30, 90)  # wait before each retry after a failed attempt
PAUSE_BETWEEN_REQUESTS_SECONDS = 2
RETRY_STATUSES = {429, 500, 502, 503, 504}
# KNBS serves an incomplete chain; this adds YE2 and Root YE (cross-signed by ISRG Root X2).
EXTRA_CA_FILE = Path(__file__).resolve().parent.parent / "certs" / "knbs-chain.pem"


def build_ssl_context():
    """certifi's roots plus EXTRA_CA_FILE, with full verification left on."""
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=EXTRA_CA_FILE)
    return context


@dataclass
class Response:
    status: int
    body: bytes
    final_url: str | None = None  # where redirects ended up


class Fetcher:
    def __init__(self):
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            verify=build_ssl_context(),
        )
        self.last_request_at = None

    def _get(self, url, min_pause):
        if self.last_request_at is not None:
            pause = max(min_pause, PAUSE_BETWEEN_REQUESTS_SECONDS)
            wait = pause - (time.monotonic() - self.last_request_at)
            if wait > 0:
                time.sleep(wait)
        try:
            return self.client.get(url)
        finally:
            self.last_request_at = time.monotonic()

    def __call__(self, url, min_pause=0):
        """Retry network errors and 429/5xx; any other status is returned as-is.

        min_pause raises the gap before each request (e.g. a site's robots.txt
        Crawl-delay); it never goes below PAUSE_BETWEEN_REQUESTS_SECONDS.
        """
        for wait in (*RETRY_WAITS_SECONDS, None):
            try:
                response = self._get(url, min_pause)
            except httpx.TransportError:
                if wait is None:
                    raise
            else:
                if response.status_code not in RETRY_STATUSES or wait is None:
                    return Response(
                        response.status_code, response.content, str(response.url)
                    )
            time.sleep(wait)


fetch = Fetcher()
