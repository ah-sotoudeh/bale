from django.db import models
from django.conf import settings
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


class Tariff(models.Model):
    """One bookable slot definition on a channel.

    start_hour makes each tariff a single daily turn (e.g. 10:00, 14:00, 22:00),
    so capacity/calendar logic stays simple: one active order per (channel, tariff, day).
    """

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='tariffs')
    name = models.CharField(max_length=100)  # e.g. "ساعت ۱۰ — ۲۴ ساعته"
    start_hour = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text='ساعت شروع نوبت در روز (0-23)؛ هر تعرفه = یک نوبت',
    )
    duration_hours = models.IntegerField()
    price = models.IntegerField(help_text='قیمت به تومان')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['channel', 'start_hour', 'duration_hours'],
                name='uniq_channel_slot_hour_duration',
                condition=models.Q(start_hour__isnull=False),
            ),
        ]

    def __str__(self):
        if self.start_hour is not None:
            return f'{self.channel.name} @ {self.start_hour:02d}:00 ({self.duration_hours}h)'
        return f'{self.channel.name} - {self.name}'


class AvailabilitySlot(models.Model):
    """Explicit busy/free windows; is_available=False blocks external bookings."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='availability')
    tariff = models.ForeignKey(
        Tariff,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='availability',
        help_text='اگر خالی باشد برای کل کانال است',
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    is_available = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['start']

    def __str__(self):
        flag = 'free' if self.is_available else 'busy'
        return f'{self.channel.name}: {self.start} - {self.end} ({flag})'
