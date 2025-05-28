from django.contrib import admin
from .models import OrderOzon, ItemInOrderOzon, OrderWB, ItemInOrderYM, OrderYM


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


class ItemInOrderYamrketInline(admin.TabularInline):
    model = ItemInOrderYM
    extra = 0
    readonly_fields = ['product', 'price', 'total_price']
    fields = ('product', 'price', 'quantity', 'total_price')

@admin.register(OrderYM)
class OrderYaAdmin(admin.ModelAdmin):
    list_display = ('number_1C', 'number_ym', 'date_create', 'price', 'exchange_1c')
    list_filter = ('exchange_1c', 'date_create')
    search_fields = ('number_ozon', 'number_1C')
    readonly_fields = ('date_create', 'price')
    inlines = [ItemInOrderYamrketInline]



@admin.register(OrderWB)
class OrderWBAdmin(admin.ModelAdmin):
    list_display = ('number_1C', 'number_WB', 'date_create', 'price', 'exchange_1c')
    search_fields = ('number_WB', 'number_1C')
    readonly_fields = ('date_create',)

    fieldsets = (
        (None, {
            'fields': ('number_WB', 'number_1C', 'price', 'exchange_1c')
        }),
        ('Привязка к товару', {
            'fields': ('content_type', 'object_id')
        }),
        ('Дополнительно', {
            'fields': ('date_create',)
        }),
    )