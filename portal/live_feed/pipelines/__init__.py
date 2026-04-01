from __future__ import annotations

from .aljazeera_live import (
    AlJazeeraLiveClient,
    build_translation_request,
    extract_children_from_ws_message,
    get_source_definition,
)
from .base import (
    BasePipelineClient,
    LiveTarget,
    PipelineSourceDefinition,
    is_breaking_item,
    parse_ws_message,
)


def get_pipeline_sources() -> list[PipelineSourceDefinition]:
    return [get_source_definition()]


def source_definition_map() -> dict[str, PipelineSourceDefinition]:
    return {item.key: item for item in get_pipeline_sources()}


def get_pipeline_client(source_key: str) -> BasePipelineClient:
    if source_key == 'aljazeera_live':
        return AlJazeeraLiveClient()
    raise ValueError(f"Unsupported pipeline source: {source_key}")


def build_pipeline_translation_request(source_key: str, *, title: str) -> dict:
    if source_key == 'aljazeera_live':
        return build_translation_request(title)
    raise ValueError(f"Unsupported pipeline source for translation request: {source_key}")


__all__ = [
    'AlJazeeraLiveClient',
    'BasePipelineClient',
    'LiveTarget',
    'PipelineSourceDefinition',
    'extract_children_from_ws_message',
    'build_pipeline_translation_request',
    'get_pipeline_client',
    'get_pipeline_sources',
    'is_breaking_item',
    'parse_ws_message',
    'source_definition_map',
]
