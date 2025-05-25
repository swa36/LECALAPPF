from django.contrib import admin
from .models import OrderOzon, ItemInOrderOzon


class ItemInOrderOzonInline(admin.TabularInline):
    model = ItemInOrderOzon
    extra = 0
    readonly_fields = ['product', 'price', 'total_price']
    fields = ('product', 'price', 'quantity', 'total_price')


@admin.register(OrderOzon)
class OrderOzonAdmin(admin.ModelAdmin):
    list_display = ('number_1C', 'number_ozon', 'date_create', 'price', 'exchange_1c')
    list_filter = ('exchange_1c', 'date_create')
    search_fields = ('number_ozon', 'number_1C')
    readonly_fields = ('date_create', 'price')
    inlines = [ItemInOrderOzonInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Пересчитываем сумму после сохранения
        obj.price = obj.calculate_total()
        obj.save()