from __future__ import annotations

import time

import httpx
from django.conf import settings

TASK_DONE = {'succeeded', 'failed', 'canceled'}


class MeiliError(Exception):
    pass


class MeiliClient:
    def __init__(self, url: str, master_key: str, timeout: float = 5.0):
        headers = {'Authorization': f'Bearer {master_key}'} if master_key else {}
        self._http = httpx.Client(base_url=url.rstrip('/'), headers=headers, timeout=timeout)

    def request(self, method: str, path: str, *, json=None, params=None, missing_ok: bool = False):
        try:
            response = self._http.request(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            raise MeiliError(f'{type(exc).__name__}: {exc}') from exc
        if missing_ok and response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise MeiliError(f'HTTP {response.status_code}: {response.text[:300]}')
        return response.json() if response.content else None

    def wait_for_task(self, task: dict, timeout: float = 120.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            result = self.request('GET', f"/tasks/{task['taskUid']}")
            if result['status'] in TASK_DONE:
                if result['status'] != 'succeeded':
                    raise MeiliError(f"Task {task['taskUid']} {result['status']}: {result.get('error')}")
                return result
            if time.monotonic() > deadline:
                raise MeiliError(f"Task {task['taskUid']} did not finish within {timeout:.0f}s")
            time.sleep(0.2)

    def is_healthy(self) -> bool:
        try:
            return (self.request('GET', '/health') or {}).get('status') == 'available'
        except MeiliError:
            return False


_client: MeiliClient | None = None


def get_client() -> MeiliClient:
    global _client
    if _client is None:
        _client = MeiliClient(settings.MEILI_URL, settings.MEILI_MASTER_KEY)
    return _client
