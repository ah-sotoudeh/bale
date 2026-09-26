from django.contrib import admin
from .models import Channel, ChannelStatSnapshot, Tariff, AvailabilitySlot

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('name', 'manager', 'members_count', 'avg_views', 'err_percent', 'stats_updated_at', 'link')
    readonly_fields = (
        'bale_peer_id',
        'members_count',
        'avg_views',
        'daily_reach',
        'posts_per_day',
        'citation_index',
        'err_percent',
        'language',
        'stats_updated_at',
        'stats_error',
    )

@admin.register(ChannelStatSnapshot)
class ChannelStatSnapshotAdmin(admin.ModelAdmin):
    list_display = ('channel', 'taken_at', 'members', 'avg_views', 'daily_reach', 'source')
    list_filter = ('source',)

@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ('channel', 'name', 'duration_hours', 'price')

@admin.register(AvailabilitySlot)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ('channel', 'start', 'end', 'is_available')
