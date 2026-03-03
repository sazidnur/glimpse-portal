from django.contrib import admin
from django.apps import apps
from django.urls import path
from django.http import JsonResponse
from django.utils.html import format_html
from django.template.response import TemplateResponse
from django.conf import settings

from api.v1.resources import news_cache, video_cache

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


CACHE_REGISTRY = [
    {"key": "news", "label": "News", "cache": news_cache, "model": "News"},
    {"key": "video", "label": "Videos", "cache": video_cache, "model": "Videos"},
]


def _get_model(name):
    return apps.get_model('supabase', name)


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
        stats['db_total'] = _get_model(entry["model"]).objects.count()
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


class VideosAdmin(admin.ModelAdmin):
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
            'placeholder="Paste YouTube URL (e.g. https://youtu.be/abc123)" '
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
                publisher.save(using='supabase')
                updated += 1
        return updated

    def fetch_missing_icons(self, request):
        Vp = _get_model('Videopublishers')
        missing = Vp.objects.using('supabase').filter(profileiconurl__isnull=True) | Vp.objects.using('supabase').filter(profileiconurl='')
        updated = self._update_icons(missing)
        return JsonResponse({'updated': updated})

    def refresh_all_icons(self, request):
        Vp = _get_model('Videopublishers')
        updated = self._update_icons(Vp.objects.using('supabase').all())
        return JsonResponse({'updated': updated})


admin.site.register(_get_model('Videos'), VideosAdmin)
admin.site.register(_get_model('Videopublishers'), VideopublishersAdmin)


class NewsAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'source', 'timestamp', 'score']
    list_per_page = 25
    search_fields = ['title', 'source', 'summary']
    list_filter = ['timestamp']


admin.site.register(_get_model('News'), NewsAdmin)


_original_get_urls = admin.AdminSite.get_urls

# --- Cloudflare Cache Analytics ---

CF_GQL_ENDPOINT = "https://api.cloudflare.com/client/v4/graphql"


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

    # Supported ranges → (minutes, bucket_unit)
    # Analytics Engine minimum bucket is 1 minute; max lookback ~3 months.
    RANGES = {
        "10m":  (10,       "minute"),
        "30m":  (30,       "minute"),
        "1h":   (60,       "minute"),
        "6h":   (360,      "minute"),
        "24h":  (1440,     "hour"),
        "7d":   (10080,    "hour"),
        "30d":  (43200,    "day"),
    }
    range_key = request.GET.get("range", "24h")
    if range_key not in RANGES:
        range_key = "24h"
    minutes, unit = RANGES[range_key]

    now = datetime.now(timezone.utc)
    from_time = (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    query = """
    {
      viewer {
        accounts(filter: { accountTag: "%s" }) {
          cache_analyticsAdaptiveGroups(
            filter: { datetime_geq: "%s", datetime_leq: "%s" }
            limit: 10000
            orderBy: [datetime_ASC]
          ) {
            sum { double1 double2 double3 }
            dimensions { ts: truncatedTime(unit: %s) }
          }
        }
      }
    }
    """ % (account_id, from_time, to_time, unit)

    try:
        req = urllib.request.Request(
            CF_GQL_ENDPOINT,
            data=json.dumps({"query": query}).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        return JsonResponse({"error": f"CF API HTTP {e.code}: {e.reason}", "detail": body}, status=502)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    errors = data.get("errors")
    if errors:
        msg = errors[0].get("message", "GraphQL error")
        # Dataset field doesn't exist yet — Worker hasn't been deployed or hasn't written data yet
        if "unknown field" in msg and "cache_analytics" in msg:
            return JsonResponse({"error": "No analytics data yet. Deploy the Cloudflare Worker and it will populate once the first writeDataPoint() flush occurs (within 60 s of traffic)."}, status=200)
        return JsonResponse({"error": f"CF GraphQL: {msg}"}, status=502)

    try:
        accounts = data.get("data", {}).get("viewer", {}).get("accounts", [])
        groups = accounts[0].get("cache_analyticsAdaptiveGroups", []) if accounts else []
    except (IndexError, KeyError, TypeError) as e:
        return JsonResponse({"error": f"Unexpected CF response shape: {e}"}, status=502)

    series = [
        {
            "ts": g["dimensions"]["ts"],
            "worker": int(g["sum"]["double1"] or 0),
            "cdn": int(g["sum"]["double2"] or 0),
            "origin": int(g["sum"]["double3"] or 0),
        }
        for g in groups
    ]

    total_worker = sum(s["worker"] for s in series)
    total_cdn = sum(s["cdn"] for s in series)
    total_origin = sum(s["origin"] for s in series)
    total_all = total_worker + total_cdn + total_origin

    return JsonResponse({
        "series": series,
        "totals": {
            "worker": total_worker,
            "cdn": total_cdn,
            "origin": total_origin,
            "total": total_all,
        },
        "unit": unit,
        "range": range_key,
        "from": from_time,
        "to": to_time,
    })




def _patched_get_urls(self):
    custom = [
        path('cache-dashboard/', self.admin_view(cache_dashboard_view), name='cache_dashboard'),
        path('cache-dashboard/stats/<str:key>/', self.admin_view(cache_stats_json), name='cache_dashboard_stats'),
        path('cache-dashboard/warm/<str:key>/', self.admin_view(cache_warm_json), name='cache_dashboard_warm'),
        path('cache-dashboard/flush/<str:key>/', self.admin_view(cache_flush_json), name='cache_dashboard_flush'),
        path('cf-analytics/', self.admin_view(cf_analytics_view), name='cf_analytics'),
        path('cf-analytics/data/', self.admin_view(cf_analytics_data_json), name='cf_analytics_data'),
    ]
    return custom + _original_get_urls(self)

admin.AdminSite.get_urls = _patched_get_urls


CUSTOM_MODELS = {'Videos', 'Videopublishers', 'News'}
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
