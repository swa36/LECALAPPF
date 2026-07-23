from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from .models import OrderOzon, ItemInOrderOzon, OrderWB, ItemInOrderYM, OrderYM, ItemInOrderAvito, OrderAvito, \
    ItemInOrderAli, OrderAli


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


class ItemInOrderAvitoInline(admin.TabularInline):
    model = ItemInOrderAvito
    extra = 0
    fields = ('linked_product', 'name_advertisement_item', 'price', 'quantity', 'total_price')
    readonly_fields = fields

    @admin.display(description='Привязанный товар')
    def linked_product(self, obj):
        if not obj.product:
            return 'Товар не найден в каталоге'
        url = reverse('admin:catalog_product_change', args=(obj.product.pk,))
        return format_html(
            '<a href="{}">{}</a><br><small>Код 1С: {} · Артикул: {}</small>',
            url,
            obj.product.name,
            obj.product.code_1C,
            obj.product.article_1C,
        )


@admin.register(OrderAvito)
class OrderAvitoAdmin(admin.ModelAdmin):
    list_display = ('number_1C', 'number_avito', 'name_advertisement', 'linked_products', 'price', 'exchange_1c')
    search_fields = ('number_1C', 'number_avito', 'name_advertisement')
    inlines = [ItemInOrderAvitoInline]

    @admin.display(description='Привязанные товары')
    def linked_products(self, obj):
        products = []
        for item in obj.items.all():
            if item.product:
                products.append((
                    reverse('admin:catalog_product_change', args=(item.product.pk,)),
                    item.product.name,
                    item.product.code_1C,
                ))
        if not products:
            return 'Товар не найден в каталоге'
        return format_html_join(
            '<br>',
            '<a href="{}">{} <small>({})</small></a>',
            products,
        )


class ItemInOrderAliInline(admin.TabularInline):
    model = ItemInOrderAli
    extra = 0


@admin.register(OrderAli)
class OrderAliAdmin(admin.ModelAdmin):
    list_display = ('number_1C', 'number_ali', 'name', 'family')
    search_fields = ('number_1C', 'number_ali', 'name', 'family')
    inlines = [ItemInOrderAliInline]
