from django.contrib import admin
from .models import Order, OrderItem, ManagerResponse

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id','customer','status','total_amount','created_at')
    inlines = [OrderItemInline]

@admin.register(ManagerResponse)
class ManagerResponseAdmin(admin.ModelAdmin):
    list_display = ('order_item','manager','action','created_at')
