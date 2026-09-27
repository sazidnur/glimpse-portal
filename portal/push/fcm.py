from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

from .message import ANDROID_CHANNEL_ID, TTL_SECONDS, PushMessage

SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'
DEFAULT_TOKEN_URI = 'https://oauth2.googleapis.com/token'
SEND_URL = 'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send'
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4


class FCMConfigError(Exception):
    pass


class FCMAuthError(Exception):
    pass


@dataclass(frozen=True)
class FCMResult:
    ok: bool
    message_id: str = ''
    error: str = ''


def build_message(message: PushMessage, *, topic: str | None = None, token: str | None = None) -> dict:
    notification = {'title': message.title, 'body': message.body}
    if message.image_url:
        notification['image'] = message.image_url
    target = {'topic': topic} if topic else {'token': token}
    return {
        **target,
        'notification': notification,
        'data': message.data,
        'android': {
            'priority': 'high',
            'ttl': f'{TTL_SECONDS}s',
            'collapse_key': message.collapse_id,
            'notification': {'channel_id': ANDROID_CHANNEL_ID},
        },
    }


class FCMClient:
    def __init__(self, *, project_id: str, service_account_file: str):
        path = Path(service_account_file)
        if not path.is_file():
            raise FCMConfigError(f'FCM service account file not found: {path}')
        try:
            info = json.loads(path.read_text(encoding='utf-8'))
            self._client_email = info['client_email']
            self._private_key = info['private_key']
        except (ValueError, KeyError) as exc:
            raise FCMConfigError(f'Invalid FCM service account file: {exc}') from exc
        self._token_uri = info.get('token_uri') or DEFAULT_TOKEN_URI
        self.project_id = project_id or info.get('project_id', '')
        if not self.project_id:
            raise FCMConfigError('FCM project id is not configured')
        self._access_token = ''
        self._expires_at = 0.0
        self._http = httpx.Client(timeout=15)

    def __enter__(self) -> FCMClient:
        return self

    def __exit__(self, *exc_info) -> None:
        self._http.close()

    def send(self, message: dict) -> FCMResult:
        url = SEND_URL.format(project_id=self.project_id)
        error = ''
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(delay)
            delay = float(2 ** attempt)
            try:
                response = self._http.post(
                    url,
                    json={'message': message},
                    headers={'Authorization': f'Bearer {self._get_access_token()}'},
                )
            except FCMAuthError as exc:
                return FCMResult(ok=False, error=str(exc))
            except httpx.HTTPError as exc:
                error = f'{type(exc).__name__}: {exc}'
                continue
            if response.status_code == 200:
                return FCMResult(ok=True, message_id=response.json().get('name', ''))
            error = _error_reason(response)
            if response.status_code == 401 and attempt == 0:
                self._access_token = ''
                delay = 0
                continue
            if response.status_code not in RETRYABLE_STATUSES:
                break
            delay = _retry_delay(response, delay)
        return FCMResult(ok=False, error=error)

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        now = int(time.time())
        assertion = jwt.encode(
            {'iss': self._client_email, 'scope': SCOPE, 'aud': self._token_uri, 'iat': now, 'exp': now + 3600},
            self._private_key,
            algorithm='RS256',
        )
        response = self._http.post(
            self._token_uri,
            data={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion},
        )
        if response.status_code != 200:
            raise FCMAuthError(f'OAuth token request failed: {_oauth_error(response)}')
        payload = response.json()
        self._access_token = payload['access_token']
        self._expires_at = now + int(payload.get('expires_in', 3600))
        return self._access_token


def _error_reason(response: httpx.Response) -> str:
    try:
        error = response.json().get('error')
    except ValueError:
        return f'HTTP {response.status_code}'
    if isinstance(error, dict):
        return f"HTTP {response.status_code} {error.get('status', '')}: {error.get('message', '')}".strip()
    return f'HTTP {response.status_code} {error or ""}'.strip()


def _oauth_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f'HTTP {response.status_code}'
    return f"HTTP {response.status_code} {payload.get('error', '')}: {payload.get('error_description', '')}".strip()


def _retry_delay(response: httpx.Response, fallback: float) -> float:
    try:
        return min(float(response.headers.get('Retry-After', '')), 30.0)
    except ValueError:
        return fallback
