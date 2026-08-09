from django.conf import settings
from django.db import models
from django.utils import timezone

from channels_app.models import Channel, Tariff


class Order(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),  # cart before checkout
        ('waiting_managers', 'WaitingManagers'),
        ('waiting_customer_confirm', 'WaitingCustomerConfirm'),  # after manager edit time
        ('waiting_payment', 'WaitingPayment'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),  # all items rejected/expired
        ('cancelled', 'Cancelled'),
    ]
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders'
    )
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='draft')
    total_amount = models.IntegerField(default=0)
    # One banner for whole order
    banner_message_id = models.CharField(max_length=255, null=True, blank=True)
    banner_from_chat_id = models.CharField(max_length=64, null=True, blank=True)
    banner_caption = models.TextField(blank=True, default='')
    managers_deadline = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Order #{self.id} by {self.customer}'

    def recompute_total(self) -> int:
        total = sum(
            i.price
            for i in self.items.exclude(manager_status__in=('rejected', 'expired'))
        )
        self.total_amount = total
        self.save(update_fields=['total_amount'])
        return total


class OrderItem(models.Model):
    MANAGER_STATUS = [
        ('cart', 'cart'),  # in draft cart
        ('pending', 'pending'),
        ('approved', 'approved'),
        ('rejected', 'rejected'),
        ('edited', 'edited'),  # manager proposed new time; awaiting customer
        ('expired', 'expired'),  # manager timeout
        ('customer_declined', 'customer_declined'),
    ]
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, null=True, blank=True)
    tariff = models.ForeignKey(Tariff, on_delete=models.CASCADE)
    requested_start = models.DateTimeField()
    requested_end = models.DateTimeField()
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    manager_status = models.CharField(max_length=20, choices=MANAGER_STATUS, default='cart')
    manager_edited_start = models.DateTimeField(null=True, blank=True)
    price = models.IntegerField(default=0)
    banner_forwarded = models.BooleanField(default=False)
    # legacy per-item banner fields kept nullable
    banner_message_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f'Item #{self.id} of Order #{self.order_id}'

    @property
    def effective_start(self):
        return self.manager_edited_start or self.requested_start


class ManagerResponse(models.Model):
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='responses')
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=20)
    payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
