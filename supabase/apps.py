from django.apps import AppConfig


class SupabaseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'supabase'
    verbose_name = 'Glimpse Data'

    def ready(self):
        from api.v1.signals import register_cache
        from api.v1.resources import news_cache, video_cache
        from .models import News, Videos

        register_cache(News, news_cache)
        register_cache(Videos, video_cache)
