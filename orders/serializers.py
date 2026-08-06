from rest_framework import serializers
from .models import Order, OrderItem

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id','channel','tariff','requested_start','requested_end','price']

class OrderCreateSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = ['id','customer','items']
        read_only_fields = ['id','customer']

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        user = self.context['request'].user
        order = Order.objects.create(customer=user, status='waiting_managers')
        total = 0
        for it in items_data:
            tariff = it['tariff']
            price = tariff.price
            oi = OrderItem.objects.create(order=order, channel=it['channel'], tariff=tariff,
                                          requested_start=it['requested_start'], requested_end=it['requested_end'],
                                          price=price, manager=it['channel'].manager)
            total += price
        order.total_amount = total
        order.save()
        # TODO: notify managers via Bale bot
        return order
