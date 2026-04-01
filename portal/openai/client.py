from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from django.conf import settings
from openai import OpenAI


def _client() -> OpenAI:
    api_key = str(getattr(settings, 'OPENAI_API_KEY', '') or '').strip()
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    return OpenAI(api_key=api_key)


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, 'model_dump'):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, 'to_dict'):
        dumped = value.to_dict()
        if isinstance(dumped, dict):
            return dumped
    return {}


def _extract_message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        chunks: list[str] = []
        for item in message:
            if isinstance(item, dict):
                if isinstance(item.get('text'), str):
                    chunks.append(item['text'])
                elif isinstance(item.get('content'), str):
                    chunks.append(item['content'])
            elif isinstance(item, str):
                chunks.append(item)
        return ''.join(chunks)
    return str(message or '')


def _extract_structured_output_from_chat_body(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get('choices')
    if not isinstance(choices, list) or not choices:
        raise RuntimeError('OpenAI response missing choices')

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get('message') if isinstance(first, dict) else {}
    content = message.get('content') if isinstance(message, dict) else None
    text = _extract_message_text(content).strip()
    if not text:
        raise RuntimeError('OpenAI response content is empty')
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'OpenAI response is not valid JSON: {text[:200]}') from exc
    if not isinstance(parsed, dict):
        raise RuntimeError('OpenAI response JSON must be an object')
    return parsed


def _build_chat_completion_body(
    *,
    model: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': json.dumps(user_payload, separators=(',', ':'), ensure_ascii=False)},
        ],
        'temperature': 0,
        'response_format': {
            'type': 'json_schema',
            'json_schema': {
                'name': 'pipeline_output',
                'strict': True,
                'schema': response_schema,
            },
        },
    }


def run_realtime_translation(
    *,
    model: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    response_schema: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    client = _client()
    body = _build_chat_completion_body(
        model=model,
        system_prompt=system_prompt,
        user_payload=user_payload,
        response_schema=response_schema,
    )
    response = client.chat.completions.create(**body)
    raw = _to_dict(response)
    parsed = _extract_structured_output_from_chat_body(raw)
    response_id = str(raw.get('id') or '')
    return parsed, response_id, raw


def create_batch(
    *,
    model: str,
    requests: list[dict[str, Any]],
) -> tuple[str, str]:
    if not requests:
        raise RuntimeError('No requests to submit')

    client = _client()
    fd, tmp_path = tempfile.mkstemp(prefix='openai_batch_', suffix='.jsonl')
    os.close(fd)
    try:
        with open(tmp_path, 'w', encoding='utf-8') as out:
            for req in requests:
                custom_id = str(req['custom_id'])
                body = _build_chat_completion_body(
                    model=model,
                    system_prompt=str(req.get('system_prompt') or ''),
                    user_payload=req.get('user_payload') or {},
                    response_schema=req.get('response_schema') or {},
                )
                line = {
                    'custom_id': custom_id,
                    'method': 'POST',
                    'url': '/v1/chat/completions',
                    'body': body,
                }
                out.write(json.dumps(line, ensure_ascii=False))
                out.write('\n')

        with open(tmp_path, 'rb') as inp:
            upload = client.files.create(file=inp, purpose='batch')

        upload_data = _to_dict(upload)
        input_file_id = str(upload_data.get('id') or '')
        if not input_file_id:
            raise RuntimeError('OpenAI did not return input file id for batch upload')

        batch = client.batches.create(
            input_file_id=input_file_id,
            endpoint='/v1/chat/completions',
            completion_window='24h',
        )
        batch_data = _to_dict(batch)
        batch_id = str(batch_data.get('id') or '')
        if not batch_id:
            raise RuntimeError('OpenAI did not return batch id')
        return batch_id, input_file_id
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def retrieve_batch(batch_id: str) -> dict[str, Any]:
    client = _client()
    response = client.batches.retrieve(str(batch_id))
    return _to_dict(response)


def cancel_batch(batch_id: str) -> dict[str, Any]:
    client = _client()
    response = client.batches.cancel(str(batch_id))
    return _to_dict(response)


def fetch_batch_output_lines(output_file_id: str) -> list[dict[str, Any]]:
    client = _client()
    raw_obj = client.files.content(str(output_file_id))
    raw_text: str

    if hasattr(raw_obj, 'text'):
        text_value = raw_obj.text
        raw_text = text_value() if callable(text_value) else str(text_value)
    else:
        maybe_content = getattr(raw_obj, 'content', raw_obj)
        if isinstance(maybe_content, bytes):
            raw_text = maybe_content.decode('utf-8', errors='replace')
        else:
            raw_text = str(maybe_content)

    rows: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def extract_structured_output_from_batch_row(row: dict[str, Any]) -> dict[str, Any]:
    response = row.get('response')
    if not isinstance(response, dict):
        raise RuntimeError('Batch row has no response object')
    body = response.get('body')
    if not isinstance(body, dict):
        raise RuntimeError('Batch response body is missing')
    return _extract_structured_output_from_chat_body(body)
