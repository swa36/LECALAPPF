import os
from django.db import models
from django.core.exceptions import ValidationError
from mptt.fields import TreeForeignKey
from mptt.models import MPTTModel


# Create your models here.

class Category(MPTTModel):
    uuid_1C = models.UUIDField(unique=True)
    name = models.TextField(verbose_name='Название')
    parent = TreeForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='children',
                            db_index=True, verbose_name='Родительская категория')
    video_instruction_url = models.URLField(
        verbose_name='Ссылка на видеоинструкцию',
        null=True,
        blank=True
    )
    file = models.FilePathField(max_length=255, path='media/video', null=True, blank=True,
                                verbose_name='Видео инструкции')


    class MPTTMeta:
        order_insertion_by = ['name']

    class Meta:
        ordering = ['name']
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'


    def __str__(self):
        return self.name



class Product(models.Model):
    uuid_1C = models.UUIDField(unique=True, editable=False, verbose_name='UUUID 1C')
    main_img_uuid = models.UUIDField(null=True, editable=False, verbose_name='UUUID main img')
    article_1C = models.CharField(max_length=255, verbose_name='Артикл 1С')
    code_1C = models.CharField(max_length=255, verbose_name='Код 1С', unique=True,)
    data_version = models.CharField(max_length=30, verbose_name='DataVersion')
    name = models.TextField(verbose_name='Наименование товара')
    description = models.TextField(verbose_name='Описание товара')
    stock = models.PositiveIntegerField(verbose_name='Остаток', default=0)
    is_archive = models.BooleanField(default=False, db_index=True,
                                     verbose_name='Архив (нет в выгрузке 1С)')
    category = TreeForeignKey(Category, null=True, on_delete=models.PROTECT, related_name='category',
                              verbose_name='Категория')



    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'

class NameAdditionalAttributes(models.Model):
    uuid_1C = models.UUIDField(unique=True, editable=False, verbose_name='UUID class_1C')
    name_attribute = models.CharField(max_length=50, verbose_name='Название атрибута')
    slug_name = models.CharField(max_length=50, verbose_name='suffix', null=True, unique=True)

    def __str__(self):
        return self.name_attribute


class ValueAdditionalAttributes(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='additional_attributes', null=True)
    attribute_name = models.ForeignKey(NameAdditionalAttributes, on_delete=models.CASCADE, null=True)
    value_attribute = models.TextField( verbose_name='Значение атрибута')

    def __str__(self):
        return f"{self.attribute_name.name_attribute}: {self.value_attribute}"


class TypePrices(models.Model):
    uuid_1C = models.UUIDField(unique=True, editable=False, verbose_name='UUID class_1C')
    type_price = models.CharField(max_length=50, verbose_name='Тип цены')
    suffix = models.CharField(max_length=50, verbose_name='Навзание полей в Prices')


class Prices(models.Model):
    product = models.OneToOneField('Product', on_delete=models.CASCADE, related_name='prices', verbose_name='Товар')
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Закупочная цена')
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Оптовая цена')
    wholesale_price_2 = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Оптовая цена 2')
    wholesale_price_3 = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Оптовая цена 3')
    retail_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Розничная цена')

    def __str__(self):
        return f"Цены для {self.product.name}"

def image_upload_path(instance, filename):
    # Гарантированно получаем артикул — продукт обязателен
    code_1C = instance.product.code_1C
    return f"img/{code_1C}/{filename}"  # например: img/ABC123/main.jpg или img/ABC123/1.jpg


class Images(models.Model):
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Продукт'
    )
    main = models.BooleanField(default=False, verbose_name='Главное изображение')
    image = models.ImageField(upload_to=image_upload_path, verbose_name='Изображение')
    filename  = models.CharField(                     # 🆕 новое поле
        max_length=255,
        db_index=True,
        verbose_name='Имя файла (без пути)',
        default=''
    )

    class Meta:
        # чтобы у одного продукта не было дубликатов по имени файла
        unique_together = ('product', 'filename')
        verbose_name = 'Изображение'
        verbose_name_plural = 'Изображения'

    def __str__(self):
        return f"{self.product.article_1C} | {'main' if self.main else os.path.basename(self.image.name)}"



class MarkUpItems(models.Model):
    wildberries_mark_up = models.IntegerField(default=12, verbose_name='Наценка ВБ')
    ozon_mark_up = models.IntegerField(default=12, verbose_name='Наценка ОЗОН')
    yandex_mark_up = models.IntegerField(default=0, verbose_name='Наценка Yandex')
    avito_mark_up = models.IntegerField(default=0, verbose_name='Наценка Авито')
    aliexpress_mark_up = models.IntegerField(default=0, verbose_name='Наценка Али')

    def clean(self):
        if not self.pk and MarkUpItems.objects.exists():
            raise ValidationError("Можно создать только одну запись наценки.")

    def __str__(self):
        return "Процент наценки"

    class Meta:
        verbose_name = 'Наценка'
        verbose_name_plural = 'Наценки'