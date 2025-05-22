from django.db import models

# Create your models here.

from django.db import models
from catalog.models import Product
# Create your models here.

class WBData(models.Model):
    product = models.OneToOneField(Product, related_name='wb', on_delete=models.CASCADE)
    offer_id = models.CharField(max_length=255, verbose_name='Индификатор продавца')
    wb_id = models.BigIntegerField(null=True, blank=True, verbose_name='ID WB')
    wb_barcode = models.BigIntegerField(null=True, blank=True, verbose_name='BARCODE WB')
    wb_item_id = models.BigIntegerField(null=True, blank=True, verbose_name='ITEMS ID WB')


    class Meta:
        verbose_name = "Данные WB"
        verbose_name_plural = "Данные WB"