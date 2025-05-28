import uuid
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone
from catalog.models import Product


class AbstractOrder(models.Model):
    number_1C = models.CharField(max_length=200, blank=True, null=True, verbose_name='Номер заказа 1C')
    date_create = models.DateTimeField(auto_now_add=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name='Сумма')
    id_contr = models.UUIDField(default='d6762066-f767-11ee-8088-00155d46f78e', editable=False)
    id_patner = models.UUIDField(default='d63b5bb6-f767-11ee-8088-00155d46f78e', editable=False)
    exchange_1c = models.BooleanField(default=False, verbose_name='Передано в 1С')

    class Meta:
        abstract = True


class AbstractOrderItem(models.Model):
    object_id = models.CharField(max_length=128, null=True)
    content_type = models.ForeignKey(ContentType, null=True, on_delete=models.RESTRICT)
    product = GenericForeignKey(ct_field='content_type', fk_field='object_id')
    form_price = models.UUIDField(verbose_name='Вид цены', null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Цена')
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Общая сумма')
    quantity = models.PositiveIntegerField(default=1, verbose_name='Количество товара')

    def save(self, *args, **kwargs):
        self.total_price = self.price * self.quantity
        super().save(*args, **kwargs)

    class Meta:
        abstract = True


class OrderAvito(AbstractOrder):
    number_avito = models.CharField(max_length=200, blank=True, null=True, verbose_name='Номер заказа авито')
    name_advertisement = models.CharField(max_length=200, blank=True, null=True, verbose_name='Название объявления')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='catalog_avito', null=True, blank=True)

    def __str__(self):
        return self.number_1C or 'Авито заказ'

    class Meta:
        verbose_name = 'Заказ Авито'
        verbose_name_plural = 'Заказы Авито'


class ItemInOrderAvito(AbstractOrderItem):
    order_num = models.ForeignKey(OrderAvito, on_delete=models.CASCADE, related_name='items', verbose_name='Номер заказа')
    name_advertisement_item = models.CharField(max_length=200, blank=True, null=True, verbose_name='Название объявления')


class OrderOzon(AbstractOrder):
    number_ozon = models.CharField(max_length=200, blank=True, null=True, verbose_name='Номер заказа Ozon')

    def __str__(self):
        return self.number_1C

    class Meta:
        verbose_name = 'Заказ Ozon'
        verbose_name_plural = 'Заказы Ozon'


class ItemInOrderOzon(AbstractOrderItem):
    order_num = models.ForeignKey(OrderOzon, on_delete=models.CASCADE, related_name='items', verbose_name='Номер заказа')


class OrderAli(AbstractOrder):
    number_ali = models.CharField(max_length=200, blank=True, null=True, verbose_name='Номер заказа Ali')
    name = models.CharField(max_length=200, blank=True, null=True, verbose_name='Имя')
    family = models.CharField(max_length=200, blank=True, null=True, verbose_name='Фамилия')

    def __str__(self):
        return self.number_1C or 'Ali заказ'

    class Meta:
        verbose_name = 'Заказ ALI'
        verbose_name_plural = 'Заказы ALI'


class ItemInOrderAli(AbstractOrderItem):
    order_num = models.ForeignKey(OrderAli, on_delete=models.CASCADE, related_name='items', verbose_name='Номер заказа')


class OrderWB(AbstractOrder):
    number_WB = models.CharField(max_length=200, blank=True, null=True, verbose_name='Номер заказа WB')
    object_id = models.CharField(max_length=128, null=True)
    content_type = models.ForeignKey(ContentType, null=True, on_delete=models.RESTRICT)
    product = GenericForeignKey(ct_field='content_type', fk_field='object_id')

    def __str__(self):
        return self.number_1C

    class Meta:
        verbose_name = 'Заказ WB'
        verbose_name_plural = 'Заказы WB'

class OrderYM(AbstractOrder):
    number_ym = models.CharField(max_length=200, blank=True, null=True, verbose_name='Номер заказа YaMarket')

    def __str__(self):
        return self.number_1C or 'YaMarket заказ'

    class Meta:
        verbose_name = 'Заказ YaMarket'
        verbose_name_plural = 'Заказы YaMarket'


class ItemInOrderYM(AbstractOrderItem):
    order_num = models.ForeignKey(OrderYM, on_delete=models.CASCADE, related_name='items', verbose_name='Номер заказа')


class MarketplaceChoices(models.TextChoices):
    OZON = 'ozon', 'Ozon'
    WB = 'wb', 'Wildberries'


class MarketplaceControl(models.Model):
    name = models.CharField(max_length=100, unique=True, choices=MarketplaceChoices.choices, verbose_name="Название")
    is_disabled = models.BooleanField(default=False, verbose_name="Отключить", help_text='Полное отключение передачи остатков')

    class Meta:
        verbose_name = "Управление маркетплейсом"
        verbose_name_plural = "Управление маркетплейсами"

    def clean(self):
        if not self.pk and MarketplaceControl.objects.count() >= 2:
            raise ValidationError("Нельзя создать больше двух маркетплейсов.")

    def __str__(self):
        return self.name.upper()

    def is_available_now(self):
        if self.is_disabled:
            return False

        now = timezone.localtime()
        now_weekday = now.weekday()

        if self.exceptions.filter(datetime_from__lte=now, datetime_to__gte=now).exists():
            return False

        for rule in self.weekly_rules.all():
            if rule.weekday == now_weekday:
                time_now = now.time()
                if rule.time_from <= time_now <= rule.time_to:
                    return False

        return True


class WeeklyRule(models.Model):
    WEEKDAYS = [(i, name) for i, name in enumerate([
        'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'
    ])]

    marketplace = models.ForeignKey(MarketplaceControl, on_delete=models.CASCADE, related_name='weekly_rules', verbose_name="Маркетплейс")
    weekday = models.IntegerField(choices=WEEKDAYS, verbose_name="День недели")
    time_from = models.TimeField(verbose_name="С времени")
    time_to = models.TimeField(verbose_name="До времени")

    class Meta:
        verbose_name = "Отключение по дню недели"
        verbose_name_plural = "Отключения по дням недели"

    def __str__(self):
        return f"{self.marketplace}: {self.get_weekday_display()} {self.time_from}–{self.time_to}"


class DateTimeException(models.Model):
    marketplace = models.ForeignKey(MarketplaceControl, on_delete=models.CASCADE, related_name='exceptions', verbose_name="Маркетплейс")
    datetime_from = models.DateTimeField(verbose_name="С")
    datetime_to = models.DateTimeField(verbose_name="По")

    class Meta:
        verbose_name = "Отключение по дате"
        verbose_name_plural = "Отключения по датам"

    def __str__(self):
        return f"{self.marketplace}: {self.datetime_from} – {self.datetime_to}"
