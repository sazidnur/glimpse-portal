from django.utils import timezone
from rest_framework import serializers

from portal.models import (
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

    class Meta:
        model = Categories
        fields = ['id', 'name', 'name_en', 'enabled', 'order', 'live_feed_type']

    def get_live_feed_type(self, obj):
        return int(getattr(obj, 'live_feed_type', 0) or 0)

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if self.get_live_feed_type(obj) > 0:
            config = getattr(obj, 'config', None)
            source = ''
            page_title = ''
            page_tagline = ''
            image_url = ''
            source_url = ''
            if isinstance(config, dict):
                source = str(config.get('source', '') or '').strip()
                page_title = str(config.get('page_title', '') or '').strip()
                page_tagline = str(config.get('page_tagline', '') or '').strip()
                image_url = str(config.get('image_url', '') or '').strip()
                source_url = str(config.get('source_url', '') or '').strip()
            data['source'] = source
            data['page_title'] = page_title
            data['page_tagline'] = page_tagline
            data['image_url'] = image_url
            data['source_url'] = source_url
        return data


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

