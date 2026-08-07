from rest_framework import serializers
from .models import Order, OrderItem
from channels_app.models import Channel, Tariff

class OrderItemSerializer(serializers.ModelSerializer):
    channel = serializers.PrimaryKeyRelatedField(queryset=Channel.objects.all())
    tariff = serializers.PrimaryKeyRelatedField(queryset=Tariff.objects.all())

    class Meta:
        model = OrderItem
        fields = ['id','channel','tariff','requested_start','requested_end','price','banner_message_id']

class OrderCreateSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = ['id','items']
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
            oi = OrderItem.objects.create(order=order, channel=channel, tariff=tariff,
                                          requested_start=it['requested_start'], requested_end=it['requested_end'],
                                          price=price, manager=channel.manager, banner_message_id=it.get('banner_message_id'))
            total += price
        order.total_amount = total
        order.save()
        # TODO: notify managers via Bale bot (send forwarded banner + action buttons)
        return order
