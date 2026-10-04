from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator


class Channel(models.Model):
    PUBLISH_MANUAL = 'manual'
    PUBLISH_BOT = 'bot'
    PUBLISH_LINKYAR = 'linkyar'
    PUBLISH_MODE_CHOICES = [
        (PUBLISH_BOT, 'ارسال خودکار با لینک‌ساز'),
        (PUBLISH_LINKYAR, 'ارسال خودکار با لینک‌یار'),
        (PUBLISH_MANUAL, 'ارسال دستی توسط خودم'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    link = models.CharField(max_length=500, blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='channels',
    )
    # نحوه انتشار تبلیغ در این کانال
    publish_mode = models.CharField(
        max_length=16,
        choices=PUBLISH_MODE_CHOICES,
        default=PUBLISH_BOT,
        help_text='bot=لینک‌ساز | linkyar=لینک‌یار | manual=دستی',
    )
    # Link Yar (user account) is admin — for auto publish via linkyar
    linkyar_is_admin = models.BooleanField(default=False)
    linkyar_checked_at = models.DateTimeField(null=True, blank=True)
    # لینک‌ساز (bot) is admin — for auto publish via Bot API
    bot_is_admin = models.BooleanField(default=False)
    bot_checked_at = models.DateTimeField(null=True, blank=True)
    manual_remind_hours = models.PositiveSmallIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(48)],
        help_text='ساعت یادآوری قبل از تبلیغ (فقط حالت دستی)',
    )
    # آمار را لینک‌یار می‌نویسد؛ مدیر وارد نمی‌کند.
    bale_peer_id = models.BigIntegerField(null=True, blank=True)
    about = models.TextField(blank=True, default='')
    language = models.CharField(max_length=16, blank=True, default='')
    members_count = models.PositiveIntegerField(default=0)
    avg_views = models.PositiveIntegerField(default=0)
    daily_reach = models.PositiveIntegerField(default=0)
    posts_per_day = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    citation_index = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    err_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    stats_updated_at = models.DateTimeField(null=True, blank=True)
    stats_error = models.CharField(max_length=255, blank=True, default='')
    is_listed = models.BooleanField(
        default=True,
        help_text='اگر False باشد از کاتالوگ مشتری مخفی است؛ سفارش‌ها می‌مانند',
    )
    # مالکیت تأییدشده توسط پشتیبان — بدون نیاز به @ در بیو
    ownership_verified = models.BooleanField(
        default=False,
        help_text='اگر True باشد پشتیبان مالک را تعیین کرده؛ چک بیو لازم نیست',
    )
    # اگر کاربر هنوز پیام نداده: منتظر username بله
    pending_manager_username = models.CharField(
        max_length=255,
        blank=True,
        default='',
        db_index=True,
        help_text='username بدون @؛ بعد از ورود کاربر به manager وصل می‌شود',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def publish_mode_label(self) -> str:
        return dict(self.PUBLISH_MODE_CHOICES).get(self.publish_mode, self.publish_mode)


class ChannelGroup(models.Model):
    """Package of channels sold/booked together (same manager, shared tariffs)."""

    name = models.CharField(max_length=200)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='channel_groups',
    )
    channels = models.ManyToManyField(Channel, related_name='groups', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def channel_count(self) -> int:
        return self.channels.count()


class Tariff(models.Model):
    """Bookable slot on a single channel OR on a ChannelGroup package."""

    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name='tariffs',
        null=True,
        blank=True,
    )
    group = models.ForeignKey(
        ChannelGroup,
        on_delete=models.CASCADE,
        related_name='tariffs',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    start_hour = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text='ساعت شروع نوبت (0-23)',
    )
    duration_hours = models.IntegerField()
    price = models.IntegerField(help_text='قیمت به تومان (برای کل مجموعه اگر group باشد)')
    is_active = models.BooleanField(
        default=True,
        help_text='اگر ادمین لازم نباشد False می‌شود و از فهرست مشتری حذف می‌شود',
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(channel__isnull=False, group__isnull=True)
                    | models.Q(channel__isnull=True, group__isnull=False)
                ),
                name='tariff_channel_xor_group',
            ),
        ]

    def clean(self):
        if bool(self.channel_id) == bool(self.group_id):
            raise ValidationError('تعرفه باید دقیقاً به یک کانال یا یک مجموعه وصل باشد.')

    def __str__(self):
        owner = self.group.name if self.group_id else (self.channel.name if self.channel_id else '?')
        return f'{owner} - {self.name}'

    @property
    def is_package(self) -> bool:
        return self.group_id is not None


class AvailabilitySlot(models.Model):
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name='availability', null=True, blank=True
    )
    group = models.ForeignKey(
        ChannelGroup, on_delete=models.CASCADE, related_name='availability', null=True, blank=True
    )
    tariff = models.ForeignKey(
        Tariff,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='availability',
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    is_available = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['start']
        indexes = [
            models.Index(fields=['tariff', 'start'], name='slot_tariff_start_idx'),
            models.Index(fields=['channel', 'start'], name='slot_channel_start_idx'),
        ]

    def __str__(self):
        flag = 'free' if self.is_available else 'busy'
        label = self.group or self.channel
        return f'{label}: {self.start} - {self.end} ({flag})'


class ChannelStatSnapshot(models.Model):
    """یک برداشت لینک‌یار. تاریخچه برای نمودار روند اعضا و بازدید."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='stat_snapshots')
    taken_at = models.DateTimeField()
    members = models.PositiveIntegerField(default=0)
    avg_views = models.PositiveIntegerField(default=0)
    daily_reach = models.PositiveIntegerField(default=0)
    posts = models.PositiveSmallIntegerField(default=0)
    forwards = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=16, default='linkyar')

    class Meta:
        ordering = ['taken_at']
        indexes = [
            models.Index(fields=['channel', 'taken_at'], name='stat_channel_taken_idx'),
        ]

    def __str__(self):
        return f'{self.channel_id} @ {self.taken_at:%Y-%m-%d %H:%M}'
