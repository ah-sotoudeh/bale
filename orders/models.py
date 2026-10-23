from django.conf import settings
from django.utils import timezone
from django.db import models

from channels_app.models import Channel, Tariff



class CustomerBusiness(models.Model):
    """پروفایل تبلیغاتی مستقل مشتری؛ از مالکیت واقعی کانال مستقل است."""
    KIND_CHOICES = [('bale', 'کانال بله'), ('external', 'کسب‌وکار خارج از بله')]
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_businesses'
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default='bale', db_index=True)
    source_ref = models.CharField(max_length=255, blank=True, default='')
    name = models.CharField(max_length=160)
    primary_topic = models.CharField(max_length=32, blank=True, default='', db_index=True)
    secondary_topics = models.JSONField(default=list, blank=True)
    avatar_url = models.URLField(max_length=1000, blank=True, default='')
    # ساختار انتخابی: {"main": ["..."], "sub": ["..."]}
    categories = models.JSONField(default=dict, blank=True)
    info_source = models.CharField(
        max_length=16, choices=[('auto', 'خودکار'), ('manual', 'دستی')], default='manual'
    )
    info_checked_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    display_name = models.CharField(max_length=160, blank=True, default='')  # شخصی‌سازی
    channel_unreachable = models.BooleanField(default=False)
    members_count = models.PositiveIntegerField(null=True, blank=True)
    active_banner = models.ForeignKey(
        'CustomerBanner', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='active_for_businesses',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['customer', 'is_deleted'], name='business_owner_deleted_idx'),
        ]

    def __str__(self):
        return f'{self.name} (customer={self.customer_id})'


class CustomerBanner(models.Model):
    """بنر ذخیره‌شده مشتری — فقط بنرهای منتشرشده در لینک‌بانک برای سفارش معتبرند."""

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='banners'
    )
    business = models.ForeignKey(
        'CustomerBusiness', on_delete=models.SET_NULL, null=True, blank=True, related_name='banners'
    )
    title = models.CharField(max_length=120, blank=True, default='')
    caption = models.TextField(blank=True, default='')
    storage_chat_id = models.CharField(max_length=64)
    storage_message_id = models.CharField(max_length=64)
    from_linkbank = models.BooleanField(default=False)
    linkbank_chat_id = models.CharField(max_length=64, blank=True, default='')
    linkbank_message_id = models.CharField(max_length=64, blank=True, default='')
    # مشخصات فوروارد لینک‌یار (rid داخلی بله — نه message_id بات)
    linkyar_rid = models.CharField(max_length=64, blank=True, default='')
    linkyar_date = models.CharField(max_length=64, blank=True, default='')
    linkyar_seq = models.CharField(max_length=32, blank=True, default='')
    # متای کپی بدون آپلود — بات و لینک‌یار
    bot_file_id = models.CharField(max_length=128, blank=True, default='')
    ly_file_id = models.CharField(max_length=64, blank=True, default='')
    ly_file_access_hash = models.CharField(max_length=64, blank=True, default='')
    ly_file_size = models.PositiveIntegerField(default=0)
    ly_file_name = models.CharField(max_length=255, blank=True, default='')
    ly_mime_type = models.CharField(max_length=80, blank=True, default='')
    media_kind = models.CharField(max_length=20, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f'Banner #{self.id} user={self.customer_id}'

    def display_title(self) -> str:
        import re
        if self.title:
            return self.title
        cap = (self.caption or '').strip().replace('\n', ' ')
        # حذف مارک‌آپ ساده بله
        cap = re.sub(r'[*_`\[\]()]', '', cap)
        cap = re.sub(r'\s+', ' ', cap).strip()
        if cap:
            return (cap[:40] + '…') if len(cap) > 40 else cap
        if (self.media_kind or '') in ('video', 'animation'):
            return 'بنر ویدیویی'
        if (self.media_kind or '') in ('photo', 'document', 'image'):
            return 'بنر تصویری'
        return f'بنر #{self.id}'



class BannerSubmissionDraft(models.Model):
    """حداکثر یک پیش‌نویس ثبت بنر ناتمام برای هر مشتری."""
    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='banner_submission_draft'
    )
    business = models.ForeignKey(
        CustomerBusiness, on_delete=models.SET_NULL, null=True, blank=True, related_name='banner_drafts'
    )
    title = models.CharField(max_length=120, blank=True, default='')
    caption = models.TextField(blank=True, default='')
    media_kind = models.CharField(max_length=20, blank=True, default='')
    media_path = models.CharField(max_length=500, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'draft customer={self.customer_id}'


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
        ('waiting_banner', 'WaitingBanner'),
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
        ('no_response', 'no_response'),
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
    publish_retry_started_at = models.DateTimeField(null=True, blank=True)
    time_change_count = models.PositiveSmallIntegerField(default=0)
    manager_reminded_at = models.DateTimeField(null=True, blank=True)

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



class SupportTicket(models.Model):
    """تیکت پشتیبانی مشتری."""
    STATUS = [
        ('open', 'open'),
        ('answered', 'answered'),
        ('customer_replied', 'customer_replied'),
        ('closed', 'closed'),
    ]
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_tickets'
    )
    subject = models.CharField(max_length=160)
    category = models.CharField(max_length=32, default='other', db_index=True)
    status = models.CharField(max_length=24, default='open', db_index=True)
    order_id_ref = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return f'Ticket #{self.id} {self.subject[:40]}'


class SupportTicketMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='ticket_messages'
    )
    body = models.TextField()
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']



class ManagerCustomerBlock(models.Model):
    """مسدودسازی مشتری توسط مدیر کانال — فقط سفارش‌های جدید."""
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocked_customers'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocked_by_managers'
    )
    note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('manager', 'customer')]


class TariffDiscount(models.Model):
    """کمپین تخفیف روی یک یا چند تعرفه — در هر لحظه فقط یک فعال per تعرفه."""
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tariff_discounts'
    )
    name = models.CharField(max_length=120, blank=True, default='')
    percent = models.PositiveSmallIntegerField(default=0)  # 0 = use fixed_amount
    fixed_amount = models.PositiveIntegerField(default=0)  # تومان کسر
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    tariffs = models.ManyToManyField('channels_app.Tariff', related_name='discounts', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def discounted_price(self, base: int) -> int:
        base = int(base or 0)
        if self.percent:
            return max(0, base - (base * int(self.percent) // 100))
        if self.fixed_amount:
            return max(0, base - int(self.fixed_amount))
        return base

    def is_live(self, now=None) -> bool:
        now = now or timezone.now()
        return bool(self.is_active and self.starts_at <= now < self.ends_at)


class ChannelReview(models.Model):
    """نظر پس از اجرای موفق — یک نظر per سفارش آیتم."""
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='channel_reviews'
    )
    channel = models.ForeignKey(
        'channels_app.Channel', on_delete=models.CASCADE, related_name='reviews'
    )
    order_item = models.OneToOneField(
        'orders.OrderItem', on_delete=models.CASCADE, related_name='review'
    )
    rating = models.PositiveSmallIntegerField()  # 1-5
    body = models.TextField(blank=True, default='')
    views_count = models.PositiveIntegerField(default=0)
    reactions_count = models.PositiveIntegerField(default=0)
    banner_link = models.CharField(max_length=500, blank=True, default='')
    tariff_name = models.CharField(max_length=120, blank=True, default='')
    executed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_hidden = models.BooleanField(default=False)
    manager_reply = models.TextField(blank=True, default='')
    manager_replied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
