from django.contrib import admin
from .models import Channel, Tariff, AvailabilitySlot

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('name', 'manager', 'link')

@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ('channel', 'name', 'duration_hours', 'price')

@admin.register(AvailabilitySlot)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ('channel', 'start', 'end', 'is_available')
