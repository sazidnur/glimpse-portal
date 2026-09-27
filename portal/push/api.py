from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from ..models import News, PushDevice, PushNotification
from . import service

SUPPORTED_TOPICS = {'breaking_news'}
PROVIDER_FOR_PLATFORM = {
    PushDevice.Platform.ANDROID: PushDevice.Provider.FCM,
    PushDevice.Platform.IOS: PushDevice.Provider.APNS,
}
MAX_DEVICE_BODY_BYTES = 16 * 1024
LIST_LIMIT = 50


class DeviceRegistrationThrottle(SimpleRateThrottle):
    scope = 'push_devices'

    def get_cache_key(self, request, view):
        ident = request.META.get('HTTP_X_CLIENT_IP') or self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class CanSendPush(BasePermission):
    def has_permission(self, request, view):
        return request.user.has_perm('data.add_pushnotification')


class DeviceRegistrationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=4096)
    platform = serializers.ChoiceField(PushDevice.Platform.choices)
    provider = serializers.ChoiceField(PushDevice.Provider.choices)
    environment = serializers.ChoiceField(PushDevice.Environment.choices)
    enabled = serializers.BooleanField()
    topics = serializers.ListField(child=serializers.CharField(max_length=64), max_length=16)
    locale = serializers.ChoiceField(['bn', 'en'])
    app_version = serializers.CharField(max_length=32)
    previous_token = serializers.CharField(max_length=4096, required=False, allow_blank=True)

    def validate_topics(self, value):
        return sorted(SUPPORTED_TOPICS.intersection(value))

    def validate(self, attrs):
        if PROVIDER_FOR_PLATFORM[attrs['platform']] != attrs['provider']:
            raise serializers.ValidationError({'provider': f"{attrs['platform']} devices must use {PROVIDER_FOR_PLATFORM[attrs['platform']]}."})
        if attrs['platform'] == PushDevice.Platform.ANDROID and attrs['environment'] != PushDevice.Environment.PRODUCTION:
            raise serializers.ValidationError({'environment': 'Android devices must use production.'})
        return attrs

    @transaction.atomic
    def save(self):
        data = dict(self.validated_data)
        token = data.pop('token')
        previous_token = data.pop('previous_token', '')
        if previous_token and previous_token != token:
            PushDevice.objects.filter(token=previous_token).delete()
        device, _ = PushDevice.objects.update_or_create(
            token=token,
            defaults={**data, 'invalidated_at': None, 'last_error': ''},
        )
        return device


class PushNotificationSerializer(serializers.ModelSerializer):
    news_id = serializers.PrimaryKeyRelatedField(
        source='news',
        queryset=News.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = PushNotification
        fields = [
            'id', 'source', 'news_id', 'title', 'body', 'image_url', 'target', 'scheduled_at',
            'idempotency_key', 'status', 'origin', 'started_at', 'finished_at',
            'fcm_message_id', 'fcm_error', 'ios_sent', 'ios_failed', 'ios_invalidated', 'ios_error',
            'created_at',
        ]
        read_only_fields = [
            'id', 'status', 'origin', 'started_at', 'finished_at',
            'fcm_message_id', 'fcm_error', 'ios_sent', 'ios_failed', 'ios_invalidated', 'ios_error',
            'created_at',
        ]
        extra_kwargs = {
            'source': {'required': False},
            'idempotency_key': {'validators': []},
        }

    def validate(self, attrs):
        attrs.setdefault(
            'source',
            PushNotification.Source.NEWS if attrs.get('news') else PushNotification.Source.CUSTOM,
        )
        candidate = PushNotification(**attrs)
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return {
            **attrs,
            'news': candidate.news,
            'title': candidate.title,
            'body': candidate.body,
            'image_url': candidate.image_url,
        }


class DeviceRegistrationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [DeviceRegistrationThrottle]

    def post(self, request):
        if len(request.body) > MAX_DEVICE_BODY_BYTES:
            return Response({'error': 'Payload too large'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        serializer = DeviceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PushNotificationListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanSendPush]

    def get(self, request):
        queryset = PushNotification.objects.all()
        if status_filter := request.query_params.get('status'):
            queryset = queryset.filter(status=status_filter)
        return Response({'items': PushNotificationSerializer(queryset[:LIST_LIMIT], many=True).data})

    def post(self, request):
        key = request.data.get('idempotency_key') if isinstance(request.data, dict) else None
        if key and (existing := PushNotification.objects.filter(idempotency_key=key).first()):
            return Response(PushNotificationSerializer(existing).data)

        serializer = PushNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notification = PushNotification(
            **serializer.validated_data,
            origin=PushNotification.Origin.API,
            created_by=request.user,
        )
        try:
            with transaction.atomic():
                service.submit(notification)
        except IntegrityError:
            existing = get_object_or_404(PushNotification, idempotency_key=key)
            return Response(PushNotificationSerializer(existing).data)
        return Response(PushNotificationSerializer(notification).data, status=status.HTTP_201_CREATED)


class PushNotificationDetailView(APIView):
    permission_classes = [IsAuthenticated, CanSendPush]

    def get(self, request, pk):
        return Response(PushNotificationSerializer(get_object_or_404(PushNotification, pk=pk)).data)


class PushNotificationCancelView(APIView):
    permission_classes = [IsAuthenticated, CanSendPush]

    def post(self, request, pk):
        notification = get_object_or_404(PushNotification, pk=pk)
        if not service.cancel(notification):
            return Response({'error': f'Cannot cancel a {notification.status} notification'}, status=status.HTTP_409_CONFLICT)
        notification.refresh_from_db()
        return Response(PushNotificationSerializer(notification).data)


class PushNotificationSendNowView(APIView):
    permission_classes = [IsAuthenticated, CanSendPush]

    def post(self, request, pk):
        notification = get_object_or_404(PushNotification, pk=pk)
        if not service.send_now(notification):
            return Response({'error': 'Only scheduled notifications can be sent early'}, status=status.HTTP_409_CONFLICT)
        notification.refresh_from_db()
        return Response(PushNotificationSerializer(notification).data)
