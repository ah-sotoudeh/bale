from django.conf import settings
from django.db import models

from channels_app.models import Channel, Tariff


class Order(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('waiting_managers', 'WaitingManagers'),
        ('waiting_customer_confirm', 'WaitingCustomerConfirm'),
        ('waiting_payment', 'WaitingPayment'),
        ('paid', 'Paid'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders'
    )
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='draft')
    total_amount = models.IntegerField(default=0)
    banner_message_id = models.CharField(max_length=255, null=True, blank=True)
    banner_from_chat_id = models.CharField(max_length=64, null=True, blank=True)
    banner_caption = models.TextField(blank=True, default='')
    banner_edit_count = models.PositiveSmallIntegerField(default=0)
    managers_deadline = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Order #{self.id} by {self.customer}'

    def recompute_total(self) -> int:
        total = sum(
            i.price
            for i in self.items.exclude(
                manager_status__in=('rejected', 'expired', 'customer_declined')
            )
        )
        self.total_amount = total
        self.save(update_fields=['total_amount'])
        return total


class OrderItem(models.Model):
    MANAGER_STATUS = [
        ('cart', 'cart'),
        ('pending', 'pending'),
        ('approved', 'approved'),
        ('rejected', 'rejected'),
        ('edited', 'edited'),
        ('expired', 'expired'),
        ('customer_declined', 'customer_declined'),
    ]
    EXECUTION_STATUS = [
        ('none', 'none'),
        ('paid', 'paid'),
        ('remind_sent', 'remind_sent'),
        ('awaiting_manager_publish', 'awaiting_manager_publish'),
        ('awaiting_customer_confirm', 'awaiting_customer_confirm'),
        ('awaiting_operator', 'awaiting_operator'),
        ('executed', 'executed'),
        ('failed_publish', 'failed_publish'),
        ('cancelled', 'cancelled'),
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
    banner_message_id = models.CharField(max_length=255, null=True, blank=True)

    execution_status = models.CharField(
        max_length=32, choices=EXECUTION_STATUS, default='none'
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_link = models.CharField(max_length=500, blank=True, default='')
    customer_confirm_deadline = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    # JSON list of posts: [{channel_id, ref, message_id, date, permalink}, ...]
    channel_message_id = models.TextField(null=True, blank=True)

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
