from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings
from websocket import create_connection

from .base import (
    BasePipelineClient,
    LiveTarget,
    PipelineSourceDefinition,
    normalize_child_ids,
    parse_ws_message,
    to_int,
)


BASE_URL = "https://www.aljazeera.com"
GRAPHQL_ENDPOINT = f"{BASE_URL}/graphql"
WS_ENDPOINT = "wss://www.aljazeera.com/_ws/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

LIVEBLOG_PATH_RE = re.compile(
    r"/news/liveblog/\d{4}/\d{1,2}/\d{1,2}/([a-z0-9-]+)", re.IGNORECASE
)
LIVEBLOG_LINK_RE = re.compile(
    r"https://www\.aljazeera\.com/news/liveblog/\d{4}/\d{1,2}/\d{1,2}/[a-z0-9-]+"
    r"|/news/liveblog/\d{4}/\d{1,2}/\d{1,2}/[a-z0-9-]+",
    re.IGNORECASE,
)

BREAKING_NEWS_QUERY = (
    "query ArchipelagoBreakingTickerQuery{"
    "breakingNews{post tickerTitle tickerText modified link}"
    "}"
)
LIVEBLOG_CHILDREN_QUERY = (
    'query SingleLiveBlogChildrensQuery($postName:String!){'
    'article:post(postName:$postName,options:{postType:"liveblog"}){'
    "id slug children"
    "}"
    "}"
)
ARCHIPELAGO_SINGLE_LIVEBLOG_QUERY = (
    "query ArchipelagoSingleLiveBlogQuery($name:String!,$postType:String,$preview:StringOrBoolean){"
    "article:post(postName:$name,options:{postType:$postType,preview:$preview}){"
    "id children"
    "}"
    "}"
)
LIVEBLOG_SUBSCRIPTION = (
    "subscription LiveBlogSubscription($postID:Int!){"
    "liveBlog(postID:$postID){id children}"
    "}"
)
LIVEBLOG_UPDATE_QUERY = (
    "query LiveBlogUpdateQuery($postID:Int!,$postType:String!,$preview:StringOrBoolean,$isAmp:Boolean){"
    "posts:postByID(id:$postID,options:{postType:$postType,preview:$preview,isAmp:$isAmp}){"
    "id "
    "link "
    "postType:type "
    "title "
    "date "
    "modified_gmt "
    "shouldDisplayTitle "
    "content "
    "author{id name slug link jobTitle} "
    "postLabel{name featuredTaxonomy}"
    "}"
    "}"
)


def get_source_definition() -> PipelineSourceDefinition:
    aljazeera_type = int(getattr(settings, 'LIVE_FEED_PIPELINE_ALJAZEERA_TYPE', 1) or 1)
    return PipelineSourceDefinition(
        key='aljazeera_live',
        label='Al Jazeera Live',
        pipeline_type=aljazeera_type,
    )


def extract_children_from_ws_message(message: dict[str, Any]) -> list[int]:
    payload = message.get("payload") or {}
    data = payload.get("data") or {}
    live_blog = data.get("liveBlog") or {}
    return normalize_child_ids(live_blog.get("children"))


class AlJazeeraLiveClient(BasePipelineClient):
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        http_timeout: float = 20.0,
        connect_timeout: float = 20.0,
        ws_timeout: float = 12.0,
    ):
        self.user_agent = user_agent
        self.http_timeout = float(http_timeout)
        self.connect_timeout = float(connect_timeout)
        self.ws_timeout = float(ws_timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "User-Agent": self.user_agent,
            "Referer": f"{BASE_URL}/",
            "Origin": BASE_URL,
            "wp-site": "aje",
            "original-domain": "www.aljazeera.com",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    def graphql_get(
        self,
        *,
        operation_name: str,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        params = {
            "wp-site": "aje",
            "operationName": operation_name,
            "query": query,
            "variables": json.dumps(variables, separators=(",", ":")),
        }
        url = f"{GRAPHQL_ENDPOINT}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.http_timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GraphQL HTTP {exc.code}: {detail[:350]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GraphQL URL error: {exc}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GraphQL returned non-JSON payload: {body[:350]}") from exc

    @staticmethod
    def normalize_liveblog_link(link: str) -> str:
        if link.startswith("http://") or link.startswith("https://"):
            return link
        if link.startswith("/"):
            return f"{BASE_URL}{link}"
        return f"{BASE_URL}/{link}"

    @staticmethod
    def slug_from_link(link: str) -> str:
        path = urllib.parse.urlparse(link).path
        match = LIVEBLOG_PATH_RE.search(path)
        if match:
            return match.group(1)
        parts = [part for part in path.split("/") if part]
        return parts[-1] if parts else ""

    def fetch_homepage_live_links(self) -> list[str]:
        request = urllib.request.Request(
            BASE_URL + "/",
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": BASE_URL + "/",
                "Accept-Language": "en-US,en;q=0.9",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.http_timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
        links = [self.normalize_liveblog_link(match.group(0)) for match in LIVEBLOG_LINK_RE.finditer(html)]
        seen: set[str] = set()
        out: list[str] = []
        for link in links:
            if link in seen:
                continue
            seen.add(link)
            out.append(link)
        return out

    def discover_latest_live_target(self) -> LiveTarget:
        payload = self.graphql_get(
            operation_name="ArchipelagoBreakingTickerQuery",
            query=BREAKING_NEWS_QUERY,
            variables={},
        )
        breaking = (payload.get("data") or {}).get("breakingNews") or {}
        raw_link = str(breaking.get("link") or "").strip()
        maybe_post_id = to_int(breaking.get("post"))

        if "/liveblog/" in raw_link:
            link = self.normalize_liveblog_link(raw_link)
            slug = self.slug_from_link(link)
            if slug:
                return LiveTarget(slug=slug, link=link, post_id=maybe_post_id)

        fallback_links = self.fetch_homepage_live_links()
        if not fallback_links:
            raise RuntimeError("Could not discover a liveblog link from breaking ticker or homepage.")

        link = fallback_links[0]
        slug = self.slug_from_link(link)
        if not slug:
            raise RuntimeError(f"Could not parse liveblog slug from link: {link}")
        return LiveTarget(slug=slug, link=link, post_id=maybe_post_id)

    def fetch_parent_and_children(
        self,
        *,
        slug: str,
        fallback_post_id: int | None = None,
    ) -> tuple[int, list[int]]:
        payload = self.graphql_get(
            operation_name="ArchipelagoSingleLiveBlogQuery",
            query=ARCHIPELAGO_SINGLE_LIVEBLOG_QUERY,
            variables={"name": slug, "postType": "liveblog", "preview": None},
        )
        errors = payload.get("errors") or []
        if errors:
            raise RuntimeError(f"ArchipelagoSingleLiveBlogQuery errors: {errors}")

        article = (payload.get("data") or {}).get("article") or {}
        post_id = to_int(article.get("id")) or fallback_post_id
        children = normalize_child_ids(article.get("children"))

        if not children:
            children_payload = self.graphql_get(
                operation_name="SingleLiveBlogChildrensQuery",
                query=LIVEBLOG_CHILDREN_QUERY,
                variables={"postName": slug},
            )
            child_errors = children_payload.get("errors") or []
            if child_errors:
                raise RuntimeError(f"SingleLiveBlogChildrensQuery errors: {child_errors}")
            child_article = (children_payload.get("data") or {}).get("article") or {}
            children = normalize_child_ids(child_article.get("children"))
            post_id = post_id or to_int(child_article.get("id")) or fallback_post_id

        if post_id is None:
            raise RuntimeError("Could not resolve liveblog parent id.")
        return post_id, children

    def fetch_children_only(self, *, slug: str) -> list[int]:
        payload = self.graphql_get(
            operation_name="SingleLiveBlogChildrensQuery",
            query=LIVEBLOG_CHILDREN_QUERY,
            variables={"postName": slug},
        )
        errors = payload.get("errors") or []
        if errors:
            raise RuntimeError(f"SingleLiveBlogChildrensQuery errors: {errors}")
        article = (payload.get("data") or {}).get("article") or {}
        return normalize_child_ids(article.get("children"))

    def fetch_live_item(self, *, child_id: int) -> dict[str, Any] | None:
        for post_type in ("liveblog-update", "liveblog"):
            payload = self.graphql_get(
                operation_name="LiveBlogUpdateQuery",
                query=LIVEBLOG_UPDATE_QUERY,
                variables={
                    "postID": int(child_id),
                    "postType": post_type,
                    "preview": None,
                    "isAmp": False,
                },
            )
            post = (payload.get("data") or {}).get("posts")
            if isinstance(post, dict) and post:
                return post
        return None

    def connect_live_ws(self, *, post_id: int):
        ws = create_connection(
            WS_ENDPOINT,
            subprotocols=["graphql-transport-ws"],
            header=[
                f"User-Agent: {self.user_agent}",
                f"Origin: {BASE_URL}",
                f"Referer: {BASE_URL}/",
            ],
            timeout=self.connect_timeout,
        )
        ws.settimeout(self.ws_timeout)

        ws.send(
            json.dumps(
                {
                    "type": "connection_init",
                    "payload": {"headers": {"wp-site": "aje", "original-domain": "www.aljazeera.com"}},
                }
            )
        )

        got_ack = False
        for _ in range(0, 12):
            message = parse_ws_message(ws.recv())
            message_type = str(message.get("type") or "")
            if message_type == "connection_ack":
                got_ack = True
                break
            if message_type == "ping":
                ws.send(json.dumps({"type": "pong"}))
        if not got_ack:
            ws.close()
            raise RuntimeError("Websocket did not return connection_ack.")

        ws.send(
            json.dumps(
                {
                    "id": f"liveblog-{post_id}",
                    "type": "subscribe",
                    "payload": {
                        "operationName": "LiveBlogSubscription",
                        "query": LIVEBLOG_SUBSCRIPTION,
                        "variables": {"postID": int(post_id)},
                    },
                }
            )
        )
        return ws
