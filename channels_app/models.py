from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator


class Channel(models.Model):
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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


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
        help_text='ساعت شروع نوبت (0-23)'
    )
    duration_hours = models.IntegerField()
    price = models.IntegerField(help_text='قیمت به تومان (برای کل مجموعه اگر group باشد)')

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

    def __str__(self):
        flag = 'free' if self.is_available else 'busy'
        label = self.group or self.channel
        return f'{label}: {self.start} - {self.end} ({flag})'
