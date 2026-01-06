"""
URL configuration for Glimpse Portal.

The portal is served at /portal/ path to coexist with WordPress at root.
API is served at /api/ path for external consumption.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

# Get the portal URL prefix from settings
portal_prefix = settings.PORTAL_URL_PREFIX

urlpatterns = [
    # Redirect /portal to /portal/ (with trailing slash)
    path(f'{portal_prefix}', RedirectView.as_view(url=f'/{portal_prefix}/', permanent=True)),

    # REST API at /portal/api/ (MUST be before admin to avoid auth redirect)
    path(f'{portal_prefix}/api/', include('supabase.urls')),

    # Main admin portal at /portal/
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

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Customize admin site
admin.site.site_header = "Glimpse Portal Admin"
admin.site.site_title = "Glimpse Portal"
admin.site.index_title = "Welcome to Glimpse Portal Administration"
