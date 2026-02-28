from django.utils import timezone
from rest_framework import serializers

from supabase.models import News, Videos


class NewsDetailSerializer(serializers.ModelSerializer):

    class Meta:
        model = News
        fields = [
            'id', 'title', 'summary', 'source', 'imageurl',
            'timestamp', 'score', 'topic', 'categoryid',
        ]
        extra_kwargs = {
            'imageurl': {'required': False},
            'timestamp': {'required': False},
            'score': {'required': False},
            'topic': {'required': False},
            'categoryid': {'required': False},
        }

    def create(self, validated_data):
        if 'timestamp' not in validated_data or validated_data['timestamp'] is None:
            validated_data['timestamp'] = timezone.now()
        return News.objects.create(**validated_data)


class VideoDetailSerializer(serializers.ModelSerializer):

    class Meta:
        model = Videos
        fields = [
            'id', 'title', 'videourl', 'source', 'publisher',
            'timestamp', 'score', 'thumbnailurl',
        ]
        extra_kwargs = {
            'videourl': {'required': False},
            'source': {'required': False},
            'publisher': {'required': False},
            'timestamp': {'required': False},
            'score': {'required': False},
            'thumbnailurl': {'required': False},
        }

    def create(self, validated_data):
        if 'timestamp' not in validated_data or validated_data['timestamp'] is None:
            validated_data['timestamp'] = timezone.now()
        return Videos.objects.create(**validated_data)
