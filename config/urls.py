from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

portal_prefix = settings.PORTAL_URL_PREFIX

urlpatterns = [
    path(f'{portal_prefix}', RedirectView.as_view(url=f'/{portal_prefix}/', permanent=True)),
    path(f'{portal_prefix}/api/', include('supabase.urls')),
    path('api/v1/', include('api.v1.urls')),
    path(f'{portal_prefix}/', admin.site.urls),
]

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

admin.site.site_header = "Glimpse Portal Admin"
admin.site.site_title = "Glimpse Portal"
admin.site.index_title = "Welcome to Glimpse Portal Administration"
admin.site.index_template = "admin/custom_index.html"
