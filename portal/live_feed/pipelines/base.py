from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PipelineSourceDefinition:
    key: str
    label: str
    pipeline_type: int


@dataclass(frozen=True)
class LiveTarget:
    slug: str
    link: str
    post_id: int | None


class BasePipelineClient(ABC):
    ws_timeout: float

    @abstractmethod
    def discover_latest_live_target(self) -> LiveTarget:
        raise NotImplementedError

    @abstractmethod
    def fetch_parent_and_children(self, *, slug: str, fallback_post_id: int | None = None) -> tuple[int, list[int]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_children_only(self, *, slug: str) -> list[int]:
        raise NotImplementedError

    @abstractmethod
    def fetch_live_item(self, *, child_id: int) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def connect_live_ws(self, *, post_id: int):
        raise NotImplementedError


def to_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def normalize_child_ids(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    out: list[int] = []
    for value in values:
        parsed = to_int(value)
        if parsed is not None:
            out.append(parsed)
    return out


def parse_ws_message(raw: Any) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_post_labels(item: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    raw = item.get("postLabel")
    if not isinstance(raw, list):
        return labels
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if name:
            labels.append(name)
    return labels


def is_breaking_item(item: dict[str, Any]) -> bool:
    direct_flag = item.get("isBreaking")
    if isinstance(direct_flag, bool):
        return direct_flag
    for label in extract_post_labels(item):
        if "breaking" in label.casefold():
            return True
    return False
