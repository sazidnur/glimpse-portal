from __future__ import annotations

from dataclasses import dataclass

ANDROID_CHANNEL_ID = 'breaking_news'
TTL_SECONDS = 3600


@dataclass(frozen=True)
class PushMessage:
    title: str
    body: str
    collapse_id: str
    image_url: str = ''
    news_id: int | None = None

    @property
    def data(self) -> dict[str, str]:
        data = {}
        if self.news_id:
            data['news_id'] = str(self.news_id)
        if self.image_url:
            data['image'] = self.image_url
        return data
