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
        fields = ['id','name','description','link','tariffs']
