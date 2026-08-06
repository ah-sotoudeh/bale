from django.db import models
from django.conf import settings
from channels_app.models import Channel, Tariff

class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('waiting_managers', 'WaitingManagers'),
        ('waiting_payment', 'WaitingPayment'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ]
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='pending')
    total_amount = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order #{self.id} by {self.customer}"

class OrderItem(models.Model):
    MANAGER_STATUS = [
        ('pending','pending'),
        ('approved','approved'),
        ('rejected','rejected'),
        ('edited','edited'),
    ]
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE)
    tariff = models.ForeignKey(Tariff, on_delete=models.CASCADE)
    requested_start = models.DateTimeField()
    requested_end = models.DateTimeField()
    banner_forwarded = models.BooleanField(default=False)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    manager_status = models.CharField(max_length=20, choices=MANAGER_STATUS, default='pending')
    manager_edited_start = models.DateTimeField(null=True, blank=True)
    price = models.IntegerField(default=0)

    def __str__(self):
        return f"Item #{self.id} of Order #{self.order.id} - {self.channel.name}"

class ManagerResponse(models.Model):
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='responses')
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=20)
    payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
