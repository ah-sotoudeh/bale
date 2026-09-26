from django.conf import settings
from django.db import models

from channels_app.models import Channel, Tariff


class CustomerBanner(models.Model):
    """بنر ذخیره‌شده مشتری — فقط بنرهای منتشرشده در لینک‌بانک برای سفارش معتبرند."""

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='banners'
    )
    title = models.CharField(max_length=120, blank=True, default='')
    caption = models.TextField(blank=True, default='')
    storage_chat_id = models.CharField(max_length=64)
    storage_message_id = models.CharField(max_length=64)
    from_linkbank = models.BooleanField(default=False)
    linkbank_chat_id = models.CharField(max_length=64, blank=True, default='')
    linkbank_message_id = models.CharField(max_length=64, blank=True, default='')
    media_kind = models.CharField(max_length=20, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f'Banner #{self.id} user={self.customer_id}'

    def display_title(self) -> str:
        if self.title:
            return self.title
        cap = (self.caption or '').strip().replace('\n', ' ')
        if cap:
            return (cap[:40] + '…') if len(cap) > 40 else cap
        return f'بنر #{self.id}'


class BannerPublishRequest(models.Model):
    """درخواست بررسی و انتشار بنر در کانال لینک‌بانک."""

    STATUS = [
        ('pending', 'pending'),
        ('approved', 'approved'),
        ('rejected', 'rejected'),
    ]
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='banner_requests'
    )
    storage_chat_id = models.CharField(max_length=64)
    storage_message_id = models.CharField(max_length=64)
    caption = models.TextField(blank=True, default='')
    media_kind = models.CharField(max_length=20, blank=True, default='')
    fee_toman = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    linkbank_message_id = models.CharField(max_length=64, blank=True, default='')
    customer_banner = models.ForeignKey(
        CustomerBanner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='publish_requests',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'BannerReq #{self.id} {self.status}'


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
    customer_banner = models.ForeignKey(
        CustomerBanner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    managers_deadline = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['customer', 'status'], name='order_customer_status_idx'),
            models.Index(fields=['status'], name='order_status_idx'),
        ]

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
    channel_message_id = models.TextField(null=True, blank=True)
    duration_hours = models.PositiveIntegerField(default=0)
    booked_channel_ids = models.JSONField(default=list, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['manager_status'], name='item_mgr_status_idx'),
            models.Index(fields=['execution_status'], name='item_exec_status_idx'),
            models.Index(fields=['tariff', 'requested_start'], name='item_tariff_start_idx'),
            models.Index(fields=['manager', 'manager_status'], name='item_manager_status_idx'),
        ]

    def __str__(self):
        return f'Item #{self.id} of Order #{self.order_id}'

    @property
    def effective_start(self):
        return self.manager_edited_start or self.requested_start

    def booked_duration(self) -> int:
        if self.duration_hours:
            return int(self.duration_hours)
        if self.tariff_id:
            return int(self.tariff.duration_hours or 0)
        return 0

    def save(self, *args, **kwargs):
        from django.db import transaction

        from orders.slots import SlotConflict, sync_item_lock

        with transaction.atomic():
            super().save(*args, **kwargs)
            if not sync_item_lock(self):
                raise SlotConflict()


class CustomerDraft(models.Model):
    """یک سبد باز برای هر مشتری. قید یکتا روی MySQL هم اعمال می‌شود."""

    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='open_draft'
    )
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='draft_lock')


class SlotReservation(models.Model):
    """قفل روزِ تعرفه. وجود ردیف یعنی آن روز فروخته شده یا دستی پر است."""

    tariff = models.ForeignKey(
        'channels_app.Tariff', on_delete=models.CASCADE, related_name='reservations'
    )
    slot_date = models.DateField()
    order_item = models.OneToOneField(
        OrderItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='slot_lock',
    )
    availability = models.OneToOneField(
        'channels_app.AvailabilitySlot',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='slot_lock',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['tariff', 'slot_date'], name='uniq_tariff_slot_date'),
            models.CheckConstraint(
                check=(
                    models.Q(order_item__isnull=False, availability__isnull=True)
                    | models.Q(order_item__isnull=True, availability__isnull=False)
                ),
                name='slot_reservation_one_owner',
            ),
        ]


class ManagerResponse(models.Model):
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='responses')
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=20)
    payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
