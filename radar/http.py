from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests

UA = "job-radar/1.0 (personal job-alert bot; polite polling of public job boards)"


class HttpError(Exception):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


class Http:
    """Thin requests wrapper: identifying User-Agent, per-host spacing, retries with
    Retry-After, and JSON validation (Lever sometimes answers with HTML)."""

    def __init__(self, timeout: float = 25, retries: int = 2, per_host_delay: float = 0.12, session=None):
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json, text/html;q=0.8, */*;q=0.5"})
        self.timeout = timeout
        self.retries = retries
        self.delay = per_host_delay
        self._next_slot: dict[str, float] = {}
        self._lock = threading.Lock()

    def _throttle(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + self.delay
        wait = slot - now
        if wait > 0:
            time.sleep(wait)

    def request(self, method: str, url: str, **kw) -> requests.Response:
        host = urlparse(url).netloc
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle(host)
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                last = HttpError(f"{host}: {e.__class__.__name__}")
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                ra = r.headers.get("Retry-After", "")
                delay = min(float(ra), 30.0) if ra.replace(".", "", 1).isdigit() else 2.0 * (attempt + 1)
                last = HttpError(f"{host}: HTTP {r.status_code}", r.status_code)
                time.sleep(delay)
                continue
            return r
        raise last or HttpError(f"{host}: failed")

    def get_text(self, url: str, **kw) -> str:
        r = self.request("GET", url, **kw)
        if r.status_code >= 400:
            raise HttpError(f"HTTP {r.status_code}", r.status_code)
        return r.text

    def get_json(self, url: str, method: str = "GET", **kw):
        for attempt in range(self.retries + 1):
            r = self.request(method, url, **kw)
            if r.status_code >= 400:
                raise HttpError(f"HTTP {r.status_code}", r.status_code)
            try:
                return r.json()
            except ValueError:
                if attempt == self.retries:
                    raise HttpError("non-JSON response", r.status_code)
                time.sleep(1.0)
