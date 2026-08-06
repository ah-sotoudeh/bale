from django.db import models
from django.conf import settings

class Channel(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    link = models.CharField(max_length=500, blank=True)  # لینک کانال
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='channels')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Tariff(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='tariffs')
    name = models.CharField(max_length=100)  # e.g., "12h", "24h", "daily", "night"
    duration_hours = models.IntegerField()
    price = models.IntegerField(help_text='price in smallest currency unit (e.g., toman)')

    def __str__(self):
        return f"{self.channel.name} - {self.name}"

class AvailabilitySlot(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='availability')
    start = models.DateTimeField()
    end = models.DateTimeField()
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ['start']

    def __str__(self):
        return f"{self.channel.name}: {self.start} - {self.end} ({'free' if self.is_available else 'booked'})"
