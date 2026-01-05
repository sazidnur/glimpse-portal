"""
Serializers for News API.
"""

from django.utils import timezone
from rest_framework import serializers
from .models import News


class NewsListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for news listings.
    Returns only essential fields with human-readable timestamp.
    """
    time_ago = serializers.SerializerMethodField()
    
    class Meta:
        model = News
        fields = ['title', 'summary', 'source', 'imageurl', 'time_ago']
    
    def get_time_ago(self, obj):
        """Convert timestamp to relative time (e.g., '5 mins ago')."""
        if not obj.timestamp:
            return ''
        
        now = timezone.now()
        diff = now - obj.timestamp
        seconds = int(diff.total_seconds())
        
        if seconds < 60:
            return 'just now'
        elif seconds < 3600:
            mins = seconds // 60
            return f'{mins} min{"s" if mins != 1 else ""} ago'
        elif seconds < 86400:
            hours = seconds // 3600
            return f'{hours} hour{"s" if hours != 1 else ""} ago'
        elif seconds < 604800:
            days = seconds // 86400
            return f'{days} day{"s" if days != 1 else ""} ago'
        elif seconds < 2592000:
            weeks = seconds // 604800
            return f'{weeks} week{"s" if weeks != 1 else ""} ago'
        else:
            return obj.timestamp.strftime('%b %d')
