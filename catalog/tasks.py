import json
from pathlib import Path
import requests
from celery import shared_task
from django.conf import settings
from django.db.models import Q
from numpy.ma.core import product
from src.lekala_class.class_1C.ExChange1C import ExChange1C
from src.lekala_class.class_1C.GetData1C import GetData1C
from catalog.models import Product, Images
from django.core.files.base import ContentFile
from ozon.models import OzonData

@shared_task
def get_data_chunck(payload):
    print("Start get data")
    data_catalog = payload['catalog']
    data1C = GetData1C()
    data1C.set_catalog_data_stock(data_catalog)
    print("END get data")


@shared_task
def get_data_1C():
    data1C = GetData1C()
    data_catalog = data1C.get_catalog()['value']
    data1C.get_price()
    data1C.get_stock()
    data1C.set_name_attribute()
    data1C.set_type_price()
    chunk_size = len(data_catalog) // 5 + (1 if len(data_catalog) % 5 else 0)
    chunks_data_catalog = [data_catalog[i:i + chunk_size] for i in range(0, len(data_catalog), chunk_size)]
    for chunk in chunks_data_catalog:
        get_data_chunck({
            'catalog': chunk,
        })



def download_img_ozon():
    file = settings.BASE_DIR / 'json' / 'ozon_image_data.json'
    with open(file, 'r', encoding='utf-8') as f:
        data_img = json.load(f)

    for items in data_img:
        for img_data in items['items']:
            product_id = img_data.get('product_id')

            try:
                product = OzonData.objects.get(ozon_id=product_id).product
            except OzonData.DoesNotExist:
                print(f"❌ Продукт с ozon_id={product_id} не найден")
                continue

            # PRIMARY PHOTO → main.jpg
            for url in img_data.get('primary_photo', []):
                try:
                    filename = "main.jpg"
                    image, created = Images.objects.get_or_create(
                        product=product,
                        filename=filename,
                        defaults={'main': True}
                    )
                    image.main = True  # гарантированно установить как главное
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        image.image.save(filename, ContentFile(response.content), save=True)
                        print(f"{'♻️ Обновлено' if not created else '✅ Сохранено'} главное изображение для {product.article_1C}")
                except Exception as e:
                    print(f"Ошибка при загрузке primary_photo: {e}")

            # PHOTO[] → 1.jpg, 2.jpg, ...
            for i, url in enumerate(img_data.get('photo', []), start=1):
                try:
                    filename = f"{i}.jpg"
                    image, created = Images.objects.get_or_create(
                        product=product,
                        filename=filename,
                        defaults={'main': False}
                    )
                    image.main = False  # явно указываем
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        image.image.save(filename, ContentFile(response.content), save=True)
                        print(f"{'♻️ Обновлено' if not created else '✅ Сохранено'} изображение {filename} для {product.article_1C}")
                except Exception as e:
                    print(f"Ошибка при загрузке photo[{i}]: {e}")




def test_get_img():
    products_without_img = Product.objects.filter(Q(ozon__isnull=True) & Q(prices__retail_price__gt = 0) & Q(
        stock__gt=0))
    print(products_without_img.count())
    c = ExChange1C()
    for product in products_without_img:
        print(f'{product.name} {product.code_1C} uuid {product.uuid_1C} id_img {product.main_img_uuid}')
        c.get_img(id_item=product.uuid_1C)
