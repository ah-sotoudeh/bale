from datetime import timedelta

from rest_framework import serializers

from channels_app.models import Channel, Tariff
from orders.availability import has_slot_conflict
from orders.models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    channel = serializers.PrimaryKeyRelatedField(queryset=Channel.objects.all())
    tariff = serializers.PrimaryKeyRelatedField(queryset=Tariff.objects.all())

    class Meta:
        model = OrderItem
        fields = [
            'id',
            'channel',
            'tariff',
            'requested_start',
            'requested_end',
            'price',
            'banner_message_id',
        ]

    def validate(self, attrs):
        channel = attrs['channel']
        tariff = attrs['tariff']
        start = attrs['requested_start']
        end = attrs['requested_end']

        if tariff.channel_id and tariff.channel_id != channel.id:
            raise serializers.ValidationError({'tariff': 'این تعرفه متعلق به این کانال نیست.'})
        if tariff.group_id and not tariff.group.channels.filter(id=channel.id).exists():
            raise serializers.ValidationError({'tariff': 'این کانال عضو مجموعه تعرفه نیست.'})

        if end <= start:
            raise serializers.ValidationError({'requested_end': 'پایان باید بعد از شروع باشد.'})

        if tariff.start_hour is not None:
            end = start + timedelta(hours=tariff.duration_hours)
            attrs['requested_end'] = end

        if has_slot_conflict(tariff, start, end, channel=channel):
            raise serializers.ValidationError(
                {'requested_start': 'این نوبت قبلاً رزرو شده یا مسدود است.'}
            )
        return attrs


class OrderCreateSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = ['id', 'items']
        read_only_fields = ['id']

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        user = self.context['request'].user
        order = Order.objects.create(customer=user, status='waiting_managers')
        total = 0
        for it in items_data:
            tariff = it['tariff']
            price = tariff.price
            channel = it['channel']
            OrderItem.objects.create(
                order=order,
                channel=channel,
                tariff=tariff,
                requested_start=it['requested_start'],
                requested_end=it['requested_end'],
                price=price,
                manager=channel.manager,
                banner_message_id=it.get('banner_message_id'),
            )
            total += price
        order.total_amount = total
        order.save()
        return order
