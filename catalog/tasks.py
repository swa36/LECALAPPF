import json
import requests
from celery import shared_task
from django.conf import settings
from src.lekala_class.class_1C.GetData1C import GetData1C
from catalog.models import Product, Images
from django.core.files.base import ContentFile
from ozon.models import OzonData

@shared_task
def get_data_chunck(payload):
    data_catalog = payload['catalog']
    data_price = payload['price']
    data_stock = payload['stock']
    data1C = GetData1C()
    data1C.set_catalog_data_stock(data_catalog, data_stock, data_price)



def get_data_1C():
    data1C = GetData1C()
    data_catalog = data1C.get_catalog()['value']
    data_price = data1C.get_price()['value']
    data_stock = data1C.get_stock()['value']

    data1C.set_name_attribute()
    data1C.set_type_price()

    chunk_size = len(data_catalog) // 5 + (1 if len(data_catalog) % 5 else 0)
    chunks_data_catalog = [data_catalog[i:i + chunk_size] for i in range(0, len(data_catalog), chunk_size)]

    for chunk in chunks_data_catalog:
        get_data_chunck.delay({
            'catalog': chunk,
            'price': data_price,
            'stock': data_stock
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
            except Product.DoesNotExist:
                print(f"❌ Продукт с code_1C={product_id} не найден")
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
                    image.main = True  # на всякий случай
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
                    image.main = False  # на всякий случай
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        image.image.save(filename, ContentFile(response.content), save=True)
                        print(f"{'♻️ Обновлено' if not created else '✅ Сохранено'} изображение {filename} для {product.article_1C}")
                except Exception as e:
                    print(f"Ошибка при загрузке photo[{i}]: {e}")

