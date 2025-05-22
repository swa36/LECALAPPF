from django.db import models
from catalog.models import Product
# Create your models here.

class OzonData(models.Model):
    product = models.OneToOneField(Product, related_name='ozon', on_delete=models.CASCADE)
    offer_id = models.CharField(max_length=255, verbose_name='Индификатор продавца')
    ozon_id = models.BigIntegerField(null=True, blank=True, verbose_name='Продукт ID OZON')
    ozon_sku = models.BigIntegerField(null=True, blank=True, verbose_name='SKU OZON')


    class Meta:
        verbose_name = "Данные OZON"
        verbose_name_plural = "Данные OZON"

