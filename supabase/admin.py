from django.contrib import admin
from django import forms
from django.apps import apps
from django.urls import path, reverse
from django.http import JsonResponse
from django.utils.html import format_html
from django.template.response import TemplateResponse
from django.conf import settings

from api.v1.resources import news_cache, video_cache, metadata_cache, rebuild_metadata_cache
from .models import (
    Categories,
    Divisions,
    News,
    Sourcealias,
    Topics,
    Videopublishers,
    Videos,
)
from .youtube import validate_youtube_shorts_url

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone


CACHE_REGISTRY = [
    {"key": "news", "label": "News", "cache": news_cache, "model": News},
    {"key": "video", "label": "Videos", "cache": video_cache, "model": Videos},
]


def _cache_by_key(key):
    for entry in CACHE_REGISTRY:
        if entry["key"] == key:
            return entry
    return None



def cache_dashboard_view(request):
    resources_json = json.dumps([{"key": e["key"], "label": e["label"]} for e in CACHE_REGISTRY])
    context = {
        **admin.site.each_context(request),
        'title': 'Redis Cache Dashboard',
        'resources_json': resources_json,
    }
    return TemplateResponse(request, 'admin/cache_dashboard.html', context)


def cache_stats_json(request, key):
    entry = _cache_by_key(key)
    if not entry:
        return JsonResponse({'error': 'Unknown cache key'}, status=404)
    try:
        stats = entry["cache"].stats()
        stats['db_total'] = entry["model"].objects.count()
        return JsonResponse(stats)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def cache_warm_json(request, key):
    entry = _cache_by_key(key)
    if not entry:
        return JsonResponse({'error': 'Unknown cache key'}, status=404)
    try:
        count = entry["cache"].warm()
        return JsonResponse({'warmed': count})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def cache_flush_json(request, key):
    entry = _cache_by_key(key)
    if not entry:
        return JsonResponse({'error': 'Unknown cache key'}, status=404)
    try:
        entry["cache"].flush()
        return JsonResponse({'flushed': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def metadata_flush_json(request):
    """Flush the metadata Redis cache. Next API request rebuilds it from DB."""
    try:
        metadata_cache.flush()
        return JsonResponse({'flushed': True, 'message': 'Metadata cache purged. Next request will rebuild from DB.'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def metadata_stats_json(request):
    try:
        stats = metadata_cache.stats()
        db_counts = {
            "categories": Categories.objects.count(),
            "topics": Topics.objects.count(),
            "divisions": Divisions.objects.count(),
            "publishers": Videopublishers.objects.count(),
            "source_aliases": Sourcealias.objects.count(),
        }
        stats["db_counts"] = db_counts
        stats["db_total"] = sum(db_counts.values())
        return JsonResponse(stats)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def metadata_rebuild_json(request):
    """Flush metadata cache then immediately rebuild it from DB."""
    try:
        metadata_cache.flush()
        rebuild_metadata_cache()
        return JsonResponse({'rebuilt': True, 'message': 'Metadata cache purged and rebuilt from DB.'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


class VideosAdmin(admin.ModelAdmin):
    class VideoAdminForm(forms.ModelForm):
        class Meta:
            model = Videos
            fields = '__all__'

        def clean_videourl(self):
            url = (self.cleaned_data.get('videourl') or '').strip()
            if not url:
                return url
            validate_youtube_shorts_url(url)
            return url

    form = VideoAdminForm

    list_display = ['id', 'title', 'publisher_name', 'timestamp', 'score', 'thumbnail_preview_small']
    list_per_page = 25
    list_select_related = ['publisher']
    ordering = ['-id']
    show_full_result_count = False
    search_fields = ['title', 'source']
    readonly_fields = [
        'id', 'title', 'videourl', 'source', 'publisher',
        'timestamp', 'score', 'thumbnailurl',
        'thumbnail_preview',
    ]
    fieldsets = (
        ('Add Video', {
            'fields': ('youtube_url_input',),
            'description': 'Paste a YouTube URL to auto-fetch video details.',
        }),
        ('Video Details', {
            'fields': ('title', 'videourl', 'source', 'publisher', 'timestamp', 'score'),
        }),
        ('Thumbnail', {
            'fields': ('thumbnailurl', 'thumbnail_preview'),
        }),
    )

    class Media:
        css = {'all': ('admin/css/videos.css',)}
        js = ('admin/js/videos.js',)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields
        return ['id', 'youtube_url_input', 'thumbnail_preview']

    def get_fieldsets(self, request, obj=None):
        if obj:
            return (
                ('Video Details', {
                    'fields': ('title', 'videourl', 'source', 'publisher', 'timestamp', 'score'),
                }),
                ('Thumbnail', {
                    'fields': ('thumbnailurl', 'thumbnail_preview'),
                }),
            )
        return self.fieldsets

    def publisher_name(self, obj):
        if obj.publisher:
            return obj.publisher.title
        return '-'
    publisher_name.short_description = 'Publisher'

    def thumbnail_preview_small(self, obj):
        if obj.thumbnailurl:
            return format_html(
                '<img src="{}" style="height:40px;border-radius:4px;" />',
                obj.thumbnailurl,
            )
        return '-'
    thumbnail_preview_small.short_description = 'Thumb'

    def thumbnail_preview(self, obj):
        if obj.thumbnailurl:
            return format_html(
                '<img src="{}" style="max-width:480px;border-radius:8px;'
                'box-shadow:0 2px 8px rgba(0,0,0,.15);" />',
                obj.thumbnailurl,
            )
        return '-'
    thumbnail_preview.short_description = 'Preview'

    def youtube_url_input(self, obj):
        return format_html(
            '<input type="text" id="youtube-url-input" '
            'placeholder="Paste Shorts URL (e.g. https://www.youtube.com/shorts/abc123def45)" '
            'style="width:100%;max-width:600px;padding:10px;font-size:14px;'
            'border:2px solid #ccc;border-radius:6px;" />'
            '<button type="button" id="fetch-youtube-btn" '
            'style="margin-left:10px;padding:10px 24px;font-size:14px;'
            'background:#417690;color:#fff;border:none;border-radius:6px;'
            'cursor:pointer;">Fetch & Save</button>'
            '<div id="youtube-fetch-status" style="margin-top:10px;"></div>'
        )
    youtube_url_input.short_description = 'YouTube URL'

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        return True

class VideopublishersAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'url', 'platform', 'icon_preview']
    list_per_page = 25
    search_fields = ['title', 'url']
    change_list_template = 'admin/supabase/videopublishers/change_list.html'

    def icon_preview(self, obj):
        if obj.profileiconurl:
            return format_html(
                '<img src="{}" style="height:24px;border-radius:50%;" />',
                obj.profileiconurl,
            )
        return '-'
    icon_preview.short_description = 'Icon'

    def get_urls(self):
        custom_urls = [
            path('fetch-missing-icons/', self.admin_site.admin_view(self.fetch_missing_icons), name='fetch_missing_icons'),
            path('refresh-all-icons/', self.admin_site.admin_view(self.refresh_all_icons), name='refresh_all_icons'),
        ]
        return custom_urls + super().get_urls()

    def _update_icons(self, queryset):
        from .youtube import fetch_channel_icon
        updated = 0
        for publisher in queryset:
            icon_url = fetch_channel_icon(publisher.url)
            if icon_url:
                publisher.profileiconurl = icon_url
                publisher.save()
                updated += 1
        return updated

    def fetch_missing_icons(self, request):
        missing = (
            Videopublishers.objects.filter(profileiconurl__isnull=True)
            | Videopublishers.objects.filter(profileiconurl='')
        )
        updated = self._update_icons(missing)
        return JsonResponse({'updated': updated})

    def refresh_all_icons(self, request):
        updated = self._update_icons(Videopublishers.objects.all())
        return JsonResponse({'updated': updated})


admin.site.register(Videos, VideosAdmin)
admin.site.register(Videopublishers, VideopublishersAdmin)


class NewsAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'source', 'timestamp', 'score']
    list_per_page = 25
    search_fields = ['title', 'source', 'summary']
    list_filter = ['timestamp']


admin.site.register(News, NewsAdmin)


class CategoriesAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'enabled', 'order', 'live_feed_type', 'live_feed_badge']
    list_editable = ['enabled', 'order', 'live_feed_type']
    list_per_page = 50
    search_fields = ['name']
    list_filter = ['enabled', 'live_feed_type']
    ordering = ['order', 'id']

    def live_feed_badge(self, obj):
        lft = getattr(obj, 'live_feed_type', 0) or 0
        if lft > 0:
            return format_html(
                '<span style="background:#28a745;color:#fff;padding:2px 8px;'
                'border-radius:4px;font-size:11px;">LIVE {}</span>',
                lft
            )
        return '-'
    live_feed_badge.short_description = 'Live'


admin.site.register(Categories, CategoriesAdmin)


_original_get_urls = admin.AdminSite.get_urls

# --- Cloudflare Cache Analytics ---


def cf_analytics_view(request):
    has_credentials = bool(
        getattr(settings, "CF_ACCOUNT_ID", "") and
        getattr(settings, "CF_ANALYTICS_TOKEN", "")
    )
    context = {
        **admin.site.each_context(request),
        "title": "Cloudflare Cache Analytics",
        "has_credentials": has_credentials,
    }
    return TemplateResponse(request, "admin/cf_analytics.html", context)


def cf_analytics_data_json(request):
    account_id = getattr(settings, "CF_ACCOUNT_ID", "")
    token = getattr(settings, "CF_ANALYTICS_TOKEN", "")
    if not account_id or not token:
        return JsonResponse({"error": "CF_ACCOUNT_ID and CF_ANALYTICS_TOKEN not configured."}, status=503)

    # Supported ranges → (WHERE interval, bucket interval, bucket unit label)
    # Analytics Engine SQL API uses ClickHouse-style INTERVAL syntax: INTERVAL '10' MINUTE
    RANGES = {
        "10m": ("'10' MINUTE", "'1' MINUTE", "minute"),
        "30m": ("'30' MINUTE", "'1' MINUTE", "minute"),
        "1h":  ("'1' HOUR",    "'1' MINUTE", "minute"),
        "6h":  ("'6' HOUR",    "'5' MINUTE", "minute"),
        "24h": ("'24' HOUR",   "'1' HOUR",   "hour"),
        "7d":  ("'7' DAY",     "'1' HOUR",   "hour"),
        "30d": ("'30' DAY",    "'1' DAY",    "day"),
    }
    range_key = request.GET.get("range", "24h")
    if range_key not in RANGES:
        range_key = "24h"
    where_interval, bucket_interval, unit = RANGES[range_key]

    sql = (
        "SELECT"
        f" toStartOfInterval(timestamp, INTERVAL {bucket_interval}) AS ts,"
        " SUM(double1) AS worker_hits,"
        " SUM(double2) AS cdn_hits,"
        " SUM(double3) AS origin_hits"
        " FROM cache_analytics"
        f" WHERE timestamp >= NOW() - INTERVAL {where_interval}"
        " GROUP BY ts ORDER BY ts ASC"
    )

    sql_endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/analytics_engine/sql"

    try:
        req = urllib.request.Request(
            sql_endpoint,
            data=sql.encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/plain",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        return JsonResponse({"error": f"CF API HTTP {e.code}: {e.reason}", "detail": body}, status=502)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    rows = data.get("data", [])
    if not rows:
        # No data yet — Worker hasn't written any data points
        now = datetime.now(timezone.utc)
        return JsonResponse({
            "series": [],
            "totals": {"worker": 0, "cdn": 0, "origin": 0, "total": 0},
            "unit": unit,
            "range": range_key,
            "from": "",
            "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "message": "No analytics data yet. Deploy the Cloudflare Worker and traffic will populate within ~60 s.",
        })

    series = []
    for row in rows:
        # Timestamps come as "YYYY-MM-DD HH:MM:SS" — convert to ISO 8601 for JS Date()
        ts_raw = row.get("ts", "")
        ts_iso = ts_raw.replace(" ", "T") + "Z" if ts_raw and "T" not in ts_raw else ts_raw
        series.append({
            "ts": ts_iso,
            "worker": int(float(row.get("worker_hits") or 0)),
            "cdn":    int(float(row.get("cdn_hits")    or 0)),
            "origin": int(float(row.get("origin_hits") or 0)),
        })

    total_worker = sum(s["worker"] for s in series)
    total_cdn    = sum(s["cdn"]    for s in series)
    total_origin = sum(s["origin"] for s in series)
    total_all    = total_worker + total_cdn + total_origin

    now = datetime.now(timezone.utc)
    return JsonResponse({
        "series": series,
        "totals": {
            "worker": total_worker,
            "cdn":    total_cdn,
            "origin": total_origin,
            "total":  total_all,
        },
        "unit":  unit,
        "range": range_key,
        "from":  series[0]["ts"] if series else "",
        "to":    now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def live_feed_dashboard_view(request):
    # Build WebSocket URL from WORKER_BASE_URL
    worker_base = (settings.WORKER_BASE_URL or '').rstrip('/')
    if worker_base.startswith('https://'):
        worker_ws_url = 'wss://' + worker_base[8:] + '/api/v1/live-feed'
    elif worker_base.startswith('http://'):
        worker_ws_url = 'ws://' + worker_base[7:] + '/api/v1/live-feed'
    else:
        worker_ws_url = 'wss://' + worker_base + '/api/v1/live-feed'

    context = {
        **admin.site.each_context(request),
        "title": "Live Feed Manager",
        "publish_url": reverse("api_live_feed_publish"),
        "token_url": reverse("api_live_feed_token"),
        "categories_url": reverse("api_live_feed_categories"),
        "items_url": reverse("api_live_feed_items"),
        "stats_url": reverse("api_live_feed_stats"),
        "category_update_url_template": reverse("api_live_feed_category_update", args=[0]).replace("/0/update/", "/__ID__/update/"),
        "category_delete_url_template": reverse("api_live_feed_category_delete", args=[0]).replace("/0/delete/", "/__ID__/delete/"),
        "worker_ws_url": worker_ws_url,
    }
    return TemplateResponse(request, "admin/live_feed_dashboard.html", context)




def _patched_get_urls(self):
    custom = [
        path('cache-dashboard/', self.admin_view(cache_dashboard_view), name='cache_dashboard'),
        path('cache-dashboard/stats/<str:key>/', self.admin_view(cache_stats_json), name='cache_dashboard_stats'),
        path('cache-dashboard/warm/<str:key>/', self.admin_view(cache_warm_json), name='cache_dashboard_warm'),
        path('cache-dashboard/flush/<str:key>/', self.admin_view(cache_flush_json), name='cache_dashboard_flush'),
        path('cache-dashboard/metadata/stats/', self.admin_view(metadata_stats_json), name='cache_dashboard_metadata_stats'),
        path('cache-dashboard/metadata/flush/', self.admin_view(metadata_flush_json), name='cache_dashboard_metadata_flush'),
        path('cache-dashboard/metadata/rebuild/', self.admin_view(metadata_rebuild_json), name='cache_dashboard_metadata_rebuild'),
        path('cf-analytics/', self.admin_view(cf_analytics_view), name='cf_analytics'),
        path('cf-analytics/data/', self.admin_view(cf_analytics_data_json), name='cf_analytics_data'),
        path('live-feed/', self.admin_view(live_feed_dashboard_view), name='live_feed_dashboard'),
    ]
    return custom + _original_get_urls(self)

admin.AdminSite.get_urls = _patched_get_urls


CUSTOM_MODELS = {'Videos', 'Videopublishers', 'News', 'Categories'}
supabase_models = apps.get_app_config('supabase').get_models()
for model in supabase_models:
    if model.__name__ in CUSTOM_MODELS:
        continue
    try:
        admin_class = type(
            f'{model.__name__}Admin',
            (admin.ModelAdmin,),
            {
                'list_display': [f.name for f in model._meta.fields[:6]],
                'search_fields': [
                    f.name for f in model._meta.fields
                    if f.get_internal_type() in ('CharField', 'TextField')
                ][:3],
                'list_per_page': 25,
            }
        )
        admin.site.register(model, admin_class)
    except admin.sites.AlreadyRegistered:
        pass
