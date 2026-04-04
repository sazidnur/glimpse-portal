from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.views.generic import RedirectView

from portal.live_feed import views

portal_prefix = settings.PORTAL_URL_PREFIX

urlpatterns = [
    path(f'{portal_prefix}', RedirectView.as_view(url=f'/{portal_prefix}/', permanent=True)),
    path(f'{portal_prefix}/api/', include('portal.urls')),
    path('origin/api/v1/', include('api.v1.urls')),  # CF Worker origin path
]

# In development, expose /api/v1/ directly (no Worker needed)
if settings.DEBUG:
    urlpatterns.insert(2, path('api/v1/', include('api.v1.urls')))
    urlpatterns += staticfiles_urlpatterns()

# Debug toolbar URLs (only in development)
if settings.DEBUG:
    try:
        import debug_toolbar
        urlpatterns = [
            path('__debug__/', include(debug_toolbar.urls)),
        ] + urlpatterns
    except ImportError:
        pass

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns.append(path(f'{portal_prefix}/live-feed/', include('portal.live_feed.urls')))
urlpatterns.append(path(f'{portal_prefix}/published-items/', views.published_items_view, name='published_items_standalone'))
urlpatterns.append(path(f'{portal_prefix}/api/published-items/', views.api_published_items, name='api_published_items_standalone'))
urlpatterns.append(path(f'{portal_prefix}/api/published-items/delete/', views.api_published_items_delete, name='api_published_items_delete_standalone'))
urlpatterns.append(path(f'{portal_prefix}/pipeline-config/', views.pipeline_manager_view, name='pipeline_config'))
urlpatterns.append(path(f'{portal_prefix}/', admin.site.urls))

admin.site.site_header = "Glimpse Portal Admin"
admin.site.site_title = "Glimpse Portal"
admin.site.index_title = "Welcome to Glimpse Portal Administration"
