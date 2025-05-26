from django.contrib import admin
from django_mptt_admin.admin import DjangoMpttAdmin

from .models import (
    Product,
    NameAdditionalAttributes,
    ValueAdditionalAttributes,
    TypePrices,
    Prices,
    Images,
    MarkUpItems, Category,
)
from django.utils.safestring import mark_safe


class ValueAdditionalAttributesInline(admin.TabularInline):
    model = ValueAdditionalAttributes
    extra = 0
    can_delete = False
    readonly_fields = ['attribute_name', 'value_attribute']
    fields = ['attribute_name', 'value_attribute']
    show_change_link = True



class ImagesInline(admin.TabularInline):
    model = Images
    extra = 1
    readonly_fields = ['preview']
    fields = ['main', 'filename', 'image', 'preview']

    def preview(self, obj):
        if obj.image:
            return mark_safe(f'<img src="{obj.image.url}" width="100" />')
        return "-"
    preview.short_description = "Превью"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'code_1C', 'article_1C', 'stock',
        'cost_price', 'wholesale_price', 'wholesale_price_2', 'wholesale_price_3', 'retail_price'
    ]
    search_fields = ['name', 'code_1C', 'article_1C']
    fields = ['uuid_1C', 'name', 'category', ('code_1C', 'article_1C', 'stock'), 'description']
    inlines = [ValueAdditionalAttributesInline, ImagesInline]
    readonly_fields = ['uuid_1C', 'code_1C', 'article_1C', 'stock']

    def cost_price(self, obj):
        return obj.prices.cost_price if hasattr(obj, 'prices') else '-'
    cost_price.short_description = "Закупочная"

    def wholesale_price(self, obj):
        return obj.prices.wholesale_price if hasattr(obj, 'prices') else '-'
    wholesale_price.short_description = "Опт 1"

    def wholesale_price_2(self, obj):
        return obj.prices.wholesale_price_2 if hasattr(obj, 'prices') else '-'
    wholesale_price_2.short_description = "Опт 2"

    def wholesale_price_3(self, obj):
        return obj.prices.wholesale_price_3 if hasattr(obj, 'prices') else '-'
    wholesale_price_3.short_description = "Опт 3"

    def retail_price(self, obj):
        return obj.prices.retail_price if hasattr(obj, 'prices') else '-'
    retail_price.short_description = "Розница"

class CategoryAdmin(DjangoMpttAdmin):
    readonly_fields = ('id',)

admin.site.register(Category, CategoryAdmin)


# @admin.register(MarkUpItems)
# class MarkUpItemsAdmin(admin.ModelAdmin):
#     list_display = ['wildberries_mark_up', 'ozon_mark_up', 'yandex_mark_up', 'avito_mark_up', 'aliexpress_mark_up']
#
#     def has_add_permission(self, request):
#         # Только одна запись допускается
#         if MarkUpItems.objects.exists():
#             return False
#         return super().has_add_permission(request)