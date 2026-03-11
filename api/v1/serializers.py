from django.utils import timezone
from rest_framework import serializers

from supabase.models import (
    News, Videos, Categories, Topics, Divisions, Videopublishers, Sourcealias,
)


class NewsDetailSerializer(serializers.ModelSerializer):

    class Meta:
        model = News
        fields = [
            'id', 'title', 'summary', 'source', 'imageurl',
            'timestamp', 'score', 'topic', 'categoryid', 'divisionid',
        ]
        extra_kwargs = {
            'imageurl': {'required': False},
            'timestamp': {'required': False},
            'score': {'required': False},
            'topic': {'required': False},
            'categoryid': {'required': False},
            'divisionid': {'required': False},
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


class CategorySerializer(serializers.ModelSerializer):
    live_feed_type = serializers.SerializerMethodField()
    is_live_feed = serializers.SerializerMethodField()

    class Meta:
        model = Categories
        fields = ['id', 'name', 'enabled', 'order', 'live_feed_type', 'is_live_feed']

    def get_live_feed_type(self, obj):
        return int(getattr(obj, 'live_feed_type', 0) or 0)

    def get_is_live_feed(self, obj):
        return self.get_live_feed_type(obj) != 0


class TopicSerializer(serializers.ModelSerializer):

    class Meta:
        model = Topics
        fields = ['id', 'name', 'order', 'enabled', 'image']


class DivisionSerializer(serializers.ModelSerializer):

    class Meta:
        model = Divisions
        fields = ['id', 'name', 'order']


class VideoPublisherSerializer(serializers.ModelSerializer):

    class Meta:
        model = Videopublishers
        fields = ['id', 'title', 'url', 'profileiconurl', 'platform']


class SourceAliasSerializer(serializers.ModelSerializer):

    class Meta:
        model = Sourcealias
        fields = ['id', 'source', 'alias', 'alias_en']
