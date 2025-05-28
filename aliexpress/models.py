from django.db import models
from catalog.models import Product
# Create your models here.

class AliData(models.Model):
    product = models.OneToOneField(Product, related_name='ali', on_delete=models.CASCADE)
    id_ali = models.BigIntegerField(null=True, blank=True, verbose_name='ID ALI')


    class Meta:
        verbose_name = "Данные AliExpress"
        verbose_name_plural = "Данные AliExpress"