from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

from .message import TTL_SECONDS, PushMessage

HOSTS = {
    'production': 'https://api.push.apple.com',
    'sandbox': 'https://api.sandbox.push.apple.com',
}
PROVIDER_TOKEN_TTL = 40 * 60
PROVIDER_TOKEN_ERRORS = {'ExpiredProviderToken', 'InvalidProviderToken'}
INVALID_TOKEN_REASONS = {'BadDeviceToken', 'Unregistered'}
MAX_ATTEMPTS = 4
CONCURRENCY = 50


class APNsConfigError(Exception):
    pass


@dataclass(frozen=True)
class APNsResult:
    token: str
    ok: bool
    reason: str = ''
    invalid: bool = False


def build_payload(message: PushMessage) -> dict:
    aps = {
        'alert': {'title': message.title, 'body': message.body},
        'sound': 'default',
    }
    if message.image_url:
        aps['mutable-content'] = 1
    return {'aps': aps, **message.data}


class APNsClient:
    def __init__(self, *, key_file: str, key_id: str, team_id: str, topic: str):
        path = Path(key_file)
        if not path.is_file():
            raise APNsConfigError(f'APNs key file not found: {path}')
        if not (key_id and team_id and topic):
            raise APNsConfigError('APNS_KEY_ID, APNS_TEAM_ID and APNS_TOPIC must be set')
        self._signing_key = path.read_text(encoding='utf-8')
        self._key_id = key_id
        self._team_id = team_id
        self._topic = topic
        self._provider_token = ''
        self._issued_at = 0.0

    def send(self, tokens_by_environment: dict[str, list[str]], message: PushMessage) -> list[APNsResult]:
        return asyncio.run(self._send_all(tokens_by_environment, message))

    async def _send_all(self, tokens_by_environment: dict[str, list[str]], message: PushMessage) -> list[APNsResult]:
        body = json.dumps(build_payload(message), ensure_ascii=False, separators=(',', ':')).encode()
        headers = {
            'apns-topic': self._topic,
            'apns-push-type': 'alert',
            'apns-priority': '10',
            'apns-expiration': str(int(time.time()) + TTL_SECONDS),
            'apns-collapse-id': message.collapse_id[:64],
            'content-type': 'application/json',
        }
        semaphore = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(http2=True, timeout=httpx.Timeout(10, connect=15)) as client:
            jobs = [
                self._send_one(client, semaphore, f'{HOSTS[environment]}/3/device/{token}', token, body, headers)
                for environment, tokens in tokens_by_environment.items()
                for token in tokens
            ]
            return await asyncio.gather(*jobs)

    async def _send_one(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        url: str,
        token: str,
        body: bytes,
        headers: dict[str, str],
    ) -> APNsResult:
        reason = ''
        async with semaphore:
            for attempt in range(MAX_ATTEMPTS):
                if attempt:
                    await asyncio.sleep(2 ** (attempt - 1))
                provider_token = self._get_provider_token()
                try:
                    response = await client.post(
                        url,
                        content=body,
                        headers={**headers, 'authorization': f'bearer {provider_token}'},
                    )
                except httpx.HTTPError as exc:
                    reason = type(exc).__name__
                    continue
                if response.status_code == 200:
                    return APNsResult(token=token, ok=True)
                reason = _reason(response)
                if response.status_code == 403 and reason in PROVIDER_TOKEN_ERRORS:
                    self._get_provider_token(stale=provider_token)
                    if attempt == 0:
                        continue
                if response.status_code == 429 or response.status_code >= 500:
                    continue
                return APNsResult(
                    token=token,
                    ok=False,
                    reason=reason,
                    invalid=response.status_code == 410 or reason in INVALID_TOKEN_REASONS,
                )
        return APNsResult(token=token, ok=False, reason=reason)

    def _get_provider_token(self, stale: str | None = None) -> str:
        expired = time.time() - self._issued_at > PROVIDER_TOKEN_TTL
        if self._provider_token and not expired and stale != self._provider_token:
            return self._provider_token
        self._issued_at = time.time()
        self._provider_token = jwt.encode(
            {'iss': self._team_id, 'iat': int(self._issued_at)},
            self._signing_key,
            algorithm='ES256',
            headers={'kid': self._key_id},
        )
        return self._provider_token


def _reason(response: httpx.Response) -> str:
    try:
        return response.json().get('reason') or f'HTTP {response.status_code}'
    except ValueError:
        return f'HTTP {response.status_code}'
