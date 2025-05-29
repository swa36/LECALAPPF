from pathlib import Path
import re
from celery import shared_task
from django.conf import settings
from django.db.models import Q
from src.lekala_class.class_1C.ExChange1C import ExChange1C
from src.lekala_class.class_1C.GetData1C import GetData1C
from catalog.models import Product
from ozon.tasks import update_remains_ozon
from wildberries.tasks import update_remains_wb
from yamarket.tasks import sent_stock_ya
from aliexpress.tasks import update_stock_ali
from django.core.files import File

@shared_task
def get_data_chunck(payload):
    print("Start get data")
    data_catalog = payload['catalog']
    data1C = GetData1C()
    data1C.set_catalog_data_stock(data_catalog)
    print("END get data")


@shared_task
def get_data_1C():
    print("START UPDATE ALL")
    data1C = GetData1C()
    data_catalog = data1C.get_catalog()['value']
    data1C.get_price()
    data1C.get_stock()
    data1C.set_name_attribute()
    data1C.set_type_price()
    data1C.set_category_catalog()
    chunk_size = len(data_catalog) // 5 + (1 if len(data_catalog) % 5 else 0)
    chunks_data_catalog = [data_catalog[i:i + chunk_size] for i in range(0, len(data_catalog), chunk_size)]
    for chunk in chunks_data_catalog:
        get_data_chunck.delay({
            'catalog': chunk,
        })
    # update_remains_ozon.delay()
    # update_remains_wb.delay()
    # sent_stock_ya.delay()
    # update_stock_ali.delay()
    




def test_get_img():
    products_without_img = Product.objects.filter(Q(ozon__isnull=True) & Q(prices__retail_price__gt = 0) & Q(
        stock__gt=0))
    print(products_without_img.count())
    c = ExChange1C()
    for product in products_without_img:
        print(f'{product.name} {product.code_1C} uuid {product.uuid_1C} id_img {product.main_img_uuid}')
        c.get_img(id_item=product.uuid_1C)


def extract_number(filename):
    match = re.search(r'(\d+)', filename)
    return int(match.group(1)) if match else float('inf')  # inf для нерелевантных



def get_img_1C():
    data_1c=ExChange1C()
    product = Product.objects.all()
    for i in product:
        data_1c.get_img(i.uuid_1C)