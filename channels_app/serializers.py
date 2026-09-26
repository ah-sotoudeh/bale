from rest_framework import serializers
from .models import Channel, Tariff, AvailabilitySlot

class TariffSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tariff
        fields = ['id','name','duration_hours','price']

class AvailabilitySlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilitySlot
        fields = ['id','start','end','is_available']

class ChannelSerializer(serializers.ModelSerializer):
    tariffs = TariffSerializer(many=True, read_only=True)

    class Meta:
        model = Channel
        fields = [
            'id',
            'name',
            'description',
            'link',
            'about',
            'language',
            'members_count',
            'avg_views',
            'daily_reach',
            'posts_per_day',
            'citation_index',
            'err_percent',
            'stats_updated_at',
            'tariffs',
        ]
        read_only_fields = [
            'about',
            'language',
            'members_count',
            'avg_views',
            'daily_reach',
            'posts_per_day',
            'citation_index',
            'err_percent',
            'stats_updated_at',
        ]
