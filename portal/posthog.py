"""Server-side PostHog queries for the admin App Analytics page.

The browser only talks to the portal, so client-side tracker blocking never hides the data.
"""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
from django.conf import settings
from django.core.cache import cache

# range key → (window, bucket function, bucket unit, cache seconds)
RANGES = {
    'live': ('60 MINUTE', 'toStartOfMinute', 'minute', 30),
    '24h': ('24 HOUR', 'toStartOfHour', 'hour', 300),
    '7d': ('7 DAY', 'toStartOfDay', 'day', 300),
    '30d': ('30 DAY', 'toStartOfDay', 'day', 300),
    '90d': ('90 DAY', 'toStartOfDay', 'day', 300),
}
STEPS = {'minute': timedelta(minutes=1), 'hour': timedelta(hours=1), 'day': timedelta(days=1)}
BUCKETS = {'live': 60, '24h': 24, '7d': 7, '30d': 30, '90d': 90}
# "Online now" and the Live map use the last 5 minutes; engagement stats need at least a day.
ONLINE_WINDOW = '5 MINUTE'
LIVE_STATS_WINDOW = '24 HOUR'
# Test and review traffic: the app's is_test_device flag (TestFlight, App Review, Play pre-launch,
# debug builds), plus models no real user owns: Android emulators and Apple's internal iPhone99,x.
TEST_FILTER = (
    "AND ifNull(toString(properties.is_test_device), '') NOT IN ('true', '1') "
    "AND NOT match(ifNull(toString(properties.$device_model), ''), "
    "'^(sdk_gphone|Android SDK built for|Standard PC|iPhone99,)')"
)
# iPadOS and macOS (iPad app on Apple silicon) run the same App Store build as iOS.
PLATFORMS = {
    'all': '',
    'ios': "AND properties.$os IN ('iOS', 'iPadOS', 'macOS')",
    'android': "AND properties.$os = 'Android'",
}

SCREEN_CAP = 1800
OS_KIND = "concat('{}:', if(properties.$os IN ('iPadOS', 'macOS'), 'iOS', ifNull(toString(properties.$os), 'Unknown')))"

class PostHogError(Exception):
    pass


def configured():
    return bool(settings.POSTHOG_PERSONAL_API_KEY and settings.POSTHOG_PROJECT_ID)


def query(sql, ttl):
    """Run a HogQL query and return its rows, cached in Redis for ``ttl`` seconds."""
    key = 'posthog:' + hashlib.sha256(sql.encode()).hexdigest()
    rows = cache.get(key)
    if rows is not None:
        return rows
    try:
        resp = httpx.post(
            f"{settings.POSTHOG_HOST.rstrip('/')}/api/projects/{settings.POSTHOG_PROJECT_ID}/query/",
            json={'query': {'kind': 'HogQLQuery', 'query': sql}, 'name': 'portal app analytics'},
            headers={'Authorization': f'Bearer {settings.POSTHOG_PERSONAL_API_KEY}'},
            timeout=30,
        )
    except httpx.HTTPError as e:
        raise PostHogError(f'PostHog unreachable: {e}') from e
    if resp.status_code != 200:
        try:
            detail = resp.json().get('detail', '')
        except ValueError:
            detail = resp.text[:300]
        raise PostHogError(f'PostHog HTTP {resp.status_code}: {detail}')
    rows = resp.json()['results']
    cache.set(key, rows, ttl)
    return rows


def fill_series(rows, now, unit, buckets):
    """Turn (bucket, users, new) rows into one point per bucket ending at ``now``, zeros included.

    Day buckets match on the date string so DST shifts can't misalign them; minute and
    hour buckets match on the instant.
    """
    now = datetime.fromisoformat(now)
    if unit == 'day':
        data = {r[0][:10]: r for r in rows}
        keys = [(now.date() - timedelta(days=i)).isoformat() for i in range(buckets - 1, -1, -1)]
        lookup = keys
    else:
        data = {datetime.fromisoformat(r[0]): r for r in rows}
        top = now.replace(second=0, microsecond=0)
        if unit == 'hour':
            top = top.replace(minute=0)
        lookup = [top - STEPS[unit] * i for i in range(buckets - 1, -1, -1)]
        keys = [t.isoformat() for t in lookup]
    return [
        {'t': k, 'users': data[l][1] if l in data else 0, 'new': data[l][2] if l in data else 0}
        for k, l in zip(keys, lookup)
    ]


def group_locations(rows):
    """(country code, country name, city, users, lat, lng) rows → countries (each with its
    cities) and a flat city list for the ranking and map markers."""
    countries, cities = {}, []
    for code, name, city, users, lat, lng in rows:
        c = countries.setdefault(code or '', {'code': code or '', 'name': name or 'Unknown', 'users': 0, 'cities': []})
        c['users'] += users
        c['cities'].append({'name': city or 'Unknown', 'users': users})
        if city:
            cities.append({'name': city, 'country': c['name'], 'code': c['code'], 'users': users, 'lat': lat, 'lng': lng})
    result = sorted(countries.values(), key=lambda c: -c['users'])
    for c in result:
        c['cities'].sort(key=lambda x: -x['users'])
    return {'countries': result, 'cities': sorted(cities, key=lambda x: -x['users'])}


def build(range_key, hide_test, platform):
    window, bucket_fn, unit, ttl = RANGES[range_key]
    filters = (TEST_FILTER if hide_test else '') + ' ' + PLATFORMS[platform]
    stats_window = LIVE_STATS_WINDOW if range_key == 'live' else window
    map_window = ONLINE_WINDOW if range_key == 'live' else window

    sql = {
        'series': (f"""
            SELECT {bucket_fn}(timestamp) AS t, count(DISTINCT person_id), countIf(event = 'onboarding_started')
            FROM events WHERE timestamp >= now() - INTERVAL {window} {filters}
            GROUP BY t ORDER BY t""", ttl),
        'summary': (f"""
            SELECT count(DISTINCT person_id), countIf(event = 'onboarding_started'),
                   count(DISTINCT if(timestamp >= now() - INTERVAL {ONLINE_WINDOW}, person_id, NULL)), now()
            FROM events WHERE timestamp >= now() - INTERVAL {window} {filters}""", ttl),
        # Each person counted once, at their latest location in the window.
        'locations': (f"""
            SELECT cc, country, city, count() AS users, avg(lat), avg(lng) FROM (
                SELECT person_id,
                       argMax(toString(properties.$geoip_country_code), timestamp) AS cc,
                       argMax(toString(properties.$geoip_country_name), timestamp) AS country,
                       argMax(toString(properties.$geoip_city_name), timestamp) AS city,
                       argMax(toFloat(properties.$geoip_latitude), timestamp) AS lat,
                       argMax(toFloat(properties.$geoip_longitude), timestamp) AS lng
                FROM events WHERE timestamp >= now() - INTERVAL {map_window} {filters}
                GROUP BY person_id)
            GROUP BY cc, country, city ORDER BY users DESC LIMIT 2000""", ttl),
        'sessions': (f"""
            SELECT sum(secs), count(), count(DISTINCT concat(toString(pid), '|', toString(d))) FROM (
                SELECT person_id AS pid, toDate(min(timestamp)) AS d,
                       dateDiff('second', min(timestamp), max(timestamp)) AS secs
                FROM events
                WHERE timestamp >= now() - INTERVAL {stats_window}
                  AND notEmpty(ifNull(toString(properties.$session_id), '')) {filters}
                GROUP BY pid, toString(properties.$session_id))""", 300),
        'features': ('SELECT kind, name, n, users FROM (' + ' UNION ALL '.join(
            f"""SELECT {kind} AS kind, ifNull({expr}, '{default}') AS name, count() AS n, count(DISTINCT person_id) AS users
                FROM events WHERE {where} AND timestamp >= now() - INTERVAL {stats_window} {filters} GROUP BY kind, name"""
            for kind, expr, default, where in [
                ("'category'", 'toString(properties.category)', 'Unknown', "event = 'category opened'"),
                # source is the article URL; group by site.
                ("'source'", "nullIf(replaceRegexpOne(domain(toString(properties.source)), '^www\\\\.', ''), '')", 'Unknown', "event = 'article opened'"),
                ("'origin'", 'toString(properties.origin)', 'feed', "event = 'article opened'"),
                ("'os'", 'toString(properties.$os)', 'Unknown', '1 = 1'),
                # Per platform, e.g. kind 'app_version:Android', 'os_version:iOS'.
                (OS_KIND.format('app_version'), 'toString(properties.$app_version)', 'Unknown', '1 = 1'),
                (OS_KIND.format('os_version'), 'toString(properties.$os_version)', 'Unknown', '1 = 1'),
            ]
        ) + ') LIMIT 5000', 300),
        'articles': (f"""
            SELECT toString(properties.article_id) AS id, countIf(event = 'article opened') AS n,
                   count(DISTINCT if(event = 'article opened', person_id, NULL)),
                   countIf(event = 'article saved'), countIf(event = 'article shared')
            FROM events
            WHERE event IN ('article opened', 'article saved', 'article shared')
              AND timestamp >= now() - INTERVAL {stats_window} {filters}
            GROUP BY id ORDER BY n DESC LIMIT 10""", 300),
        # screen time comes only from the app's TrackScreen ($screen also has OS activity names).
        # shortcut: each visit capped at 30 min because the timer keeps running while the app is
        # backgrounded on that screen; drop the cap once the app stops it on background.
        'screens': (f"""
            SELECT ifNull(toString(properties.screen), 'Unknown') AS name, count(), count(DISTINCT person_id),
                   sum(least(toFloat(properties.duration_seconds), {SCREEN_CAP})),
                   quantile(0.5)(least(toFloat(properties.duration_seconds), {SCREEN_CAP}))
            FROM events WHERE event = 'screen time' AND timestamp >= now() - INTERVAL {stats_window} {filters}
            GROUP BY name ORDER BY 4 DESC LIMIT 20""", 300),
        'engagement': (f"""
            SELECT countIf(event = 'article opened'),
                   countIf(event = 'article saved'), count(DISTINCT if(event = 'article saved', person_id, NULL)),
                   countIf(event = 'article shared'), count(DISTINCT if(event = 'article shared', person_id, NULL)),
                   countIf(event = 'video watched'), count(DISTINCT if(event = 'video watched', person_id, NULL)),
                   avgIf(least(toFloat(properties.watched_seconds), 3600), event = 'video watched'),
                   avgIf(least(toFloat(properties.percent_watched), 100), event = 'video watched'),
                   countIf(event = 'video watched' AND toFloat(properties.percent_watched) >= 90)
            FROM events
            WHERE event IN ('article opened', 'article saved', 'article shared', 'video watched')
              AND timestamp >= now() - INTERVAL {stats_window} {filters}""", 300),
        # Installs (onboarding_started) from the last 90 days; day N counts only once it has fully passed.
        'retention': (f"""
            SELECT count(),
                   countIf(addDays(first, 1) < today()), countIf(has(days, addDays(first, 1))),
                   countIf(addDays(first, 7) < today()), countIf(has(days, addDays(first, 7))),
                   countIf(addDays(first, 30) < today()), countIf(has(days, addDays(first, 30)))
            FROM (
                SELECT person_id, minIf(toDate(timestamp), event = 'onboarding_started') AS first,
                       groupUniqArray(toDate(timestamp)) AS days, countIf(event = 'onboarding_started') AS installs
                FROM events WHERE timestamp >= now() - INTERVAL 121 DAY {filters}
                GROUP BY person_id)
            WHERE installs > 0 AND first >= addDays(today(), -90)""", 300),
        'stickiness': (f"""
            SELECT count(DISTINCT person_id), count(DISTINCT concat(toString(person_id), '|', toString(toDate(timestamp))))
            FROM events WHERE timestamp >= now() - INTERVAL 30 DAY {filters}""", 300),
    }
    # PostHog allows 3 concurrent queries per project.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(query, s, t) for name, (s, t) in sql.items()}
        r = {name: f.result() for name, f in futures.items()}

    users, new, online, now = r['summary'][0]
    secs, sessions, user_days = r['sessions'][0] if r['sessions'] else (0, 0, 0)
    ret = r['retention'][0] if r['retention'] else (0,) * 7
    mau, mau_days = r['stickiness'][0] if r['stickiness'] else (0, 0)
    opened, saves, savers, shares, sharers, videos, viewers, watch_secs, watch_pct, completed = r['engagement'][0]

    features = {}
    for kind, name, n, u in sorted(r['features'], key=lambda row: (-row[3], -row[2])):
        features.setdefault(kind, []).append({'name': name, 'count': n, 'users': u})

    def rate(eligible, kept):
        return round(kept / eligible * 100, 1) if eligible else None

    return {
        'range': range_key,
        'unit': unit,
        'series': fill_series(r['series'], now, unit, BUCKETS[range_key]),
        'totals': {
            'online': online,
            'users': users,
            'new': new,
            'avg_session_secs': round((secs or 0) / sessions) if sessions else None,
            'avg_secs_per_user_day': round((secs or 0) / user_days) if user_days else None,
            'dau': round(mau_days / 30, 1),
            'mau': mau,
            'stickiness': round(mau_days / 30 / mau * 100, 1) if mau else None,
        },
        'retention': {
            'cohort': ret[0],
            'd1': rate(ret[1], ret[2]),
            'd7': rate(ret[3], ret[4]),
            'd30': rate(ret[5], ret[6]),
        },
        'locations': group_locations(r['locations']),
        'features': {k: v[:10] for k, v in features.items()},
        'articles': [
            {'id': a, 'count': n, 'users': u, 'saves': sv, 'shares': sh} for a, n, u, sv, sh in r['articles']
        ],
        'screens': [
            {'name': name, 'count': n, 'users': u, 'total_secs': round(total or 0),
             'median_secs': round(med or 0), 'secs_per_user': round((total or 0) / u) if u else 0}
            for name, n, u, total, med in r['screens']
        ],
        'engagement': {
            'opened': opened, 'saves': saves, 'savers': savers, 'shares': shares, 'sharers': sharers,
            'save_rate': rate(opened, saves), 'share_rate': rate(opened, shares),
            'videos': videos, 'viewers': viewers,
            'avg_watch_secs': round(watch_secs) if watch_secs is not None else None,
            'avg_watch_pct': round(watch_pct, 1) if watch_pct is not None else None,
            'completion_rate': rate(videos, completed),
        },
    }
