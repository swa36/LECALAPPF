import time

from celery import shared_task
import requests
import lekala_ppf.settings as settings
from catalog.models import Product, MarkUpItems, TypePrices, Images
import json
from order.models import OrderOzon, ItemInOrderOzon
from ozon.models import OzonData
from src.lekala_class.class_marketplace.OzonExchange import OzonExchange
from pathlib import Path
from src.lekala_class.class_marketplace.OzonItem import OzonTapeOutSaloon, OzonTapeInSaloon, OzonProtectGlass
from django.db.models import Q, Count
from django.core.files.base import ContentFile
import pandas as pd

def get_data_csv_ozon():
    filename = settings.BASE_DIR / 'src' / 'OzonData' / 'all_data_ozon.csv'
    # Оставляем только нужные столбцы
    df = pd.read_csv(filename, sep=';', encoding='utf-8')
    df["Артикул"] = df["Артикул"].astype(str).str.lstrip("'")
    # Оставляем нужные колонки
    columns = ["Артикул", "Ozon Product ID", "SKU", "Название товара"]
    values = df[columns].to_dict(orient='records')
    r = 0
    for i in values:
        product = None
        try:
            product = Product.objects.get(name=i['Название товара'])
        except Product.DoesNotExist:
            try:
                product = Product.objects.get(name__icontains=i['Название товара'])
            except Product.DoesNotExist:
                print(i['Название товара'])
                r += 1
        except Product.MultipleObjectsReturned:
            print(f'{i['Название товара']} дубль')
            r += 1
        if product:
            OzonData.objects.update_or_create(
                product=product,
                defaults={
                    'offer_id': i['Артикул'],
                    'ozon_id': i['Ozon Product ID'],
                    'ozon_sku': i['SKU'],
                }
            )


def ozon_get_img():
    ozon_items = OzonData.objects.all()
    ozon_exchange = OzonExchange()
    product_id_list = []
    results = []

    for item in ozon_items:
        product_id_list.append(item.ozon_id)
        if len(product_id_list) == 1000:
            try:
                img_data = ozon_exchange.get_img_ozon(product_id_list)
                results.append(img_data)
                print(f"Fetched batch of 1000: {len(img_data)} items")
            except Exception as e:
                print(f"Error fetching batch: {e}")
            product_id_list.clear()

    if product_id_list:
        try:
            img_data = ozon_exchange.get_img_ozon(product_id_list)
            results.append(img_data)
            print(f"Fetched final batch: {len(img_data)} items")
        except Exception as e:
            print(f"Error fetching final batch: {e}")

    # Сохраняем в JSON
    output_path = Path('json/ozon_image_data.json')
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Saved all image data to {output_path.resolve()}")

def download_img_ozon():
    ozon_get_img()
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

            # ✅ Удаляем все файлы в media/img/{product.code_1C}
            product_folder = Path(settings.MEDIA_ROOT) / 'img' / product.code_1C
            if product_folder.exists() and product_folder.is_dir():
                for file in product_folder.iterdir():
                    if file.is_file():
                        file.unlink()
                print(f"🗑️ Удалена папка изображений: {product_folder}")

            # PRIMARY PHOTO → main.jpg
            for url in img_data.get('primary_photo', []):
                try:
                    filename = "main.jpg"
                    image, _ = Images.objects.get_or_create(
                        product=product,
                        filename=filename,
                        defaults={'main': True}
                    )
                    image.main = True
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        image.image.save(filename, ContentFile(response.content), save=True)
                        print(f"✅ Главное изображение для {product.code_1C}")
                except Exception as e:
                    print(f"❌ Ошибка primary_photo: {e}")

            # PHOTO[] → 1.jpg, 2.jpg, ...
            for i, url in enumerate(img_data.get('photo', []), start=1):
                try:
                    filename = f"{i}.jpg"
                    image, _ = Images.objects.get_or_create(
                        product=product,
                        filename=filename,
                        defaults={'main': False}
                    )
                    image.main = False
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        image.image.save(filename, ContentFile(response.content), save=True)
                        print(f"✅ Изображение {filename} для {product.article_1C}")
                except Exception as e:
                    print(f"❌ Ошибка photo[{i}]: {e}")

def add_new_item_ozon():
    ozon_api = OzonExchange()
    items = []
    products_not_ozon = Product.objects.annotate(image_count=Count('images')).filter(
        Q(image_count__gt=0) & Q(ozon__isnull=False) & Q(prices__retail_price__gt=0)
    )
    for product in products_not_ozon:
        if len(items) > 99:
            ozon_api.post_items(data=items)
            items.clear()
        try:
            ozon_item = OzonItemFactory(product).create()
            items.append(ozon_item.item())
        except ValueError as e:
            pass
    if len(items) > 0:
        ozon_api.post_items(data=items)


@shared_task
def update_price_ozon():
    ozon_api = OzonExchange()
    ozon_data = OzonData.objects.all().values_list('offer_id', 'ozon_id', 'product__prices__retail_price')
    mark_up = MarkUpItems.objects.last()
    data_price = []

    for item in ozon_data:
        base_price = int(item[2])
        raw_price = base_price + (mark_up.ozon_mark_up * base_price) / 100
        final_price = ozon_api.round_to_nearest_10_custom(raw_price)

        item_price_info = {
            "auto_action_enabled": "DISABLED",
            "auto_add_to_ozon_actions_list_enabled":"DISABLED",
            "currency_code": "RUB",
            "price_strategy_enabled": "DISABLED",
            "min_price": str(final_price),
            "offer_id": item[0],
            "old_price": "0",
            "price": str(final_price),
            "product_id": item[1],
            "vat": "0",
            "quant_size":"1"
        }

        data_price.append(item_price_info)

        if len(data_price) >= 1000:
            ozon_api.update_price(data=data_price)
            data_price.clear()

    if data_price:
        ozon_api.update_price(data=data_price)


def set_ozon_prod_and_sku():
    ozon_api = OzonExchange()
    products_not_ozon = Product.objects.filter(ozon__isnull=True).values_list('code_1C')
    list_article = []
    for items in products_not_ozon:
        if len(list_article) > 999:
            info_ozon = ozon_api.get_items(data=list_article)
            ozon_api.set_num_sku_id_ozon(info_ozon)
            list_article.clear()
        if items[0]:
            list_article.append(items[0])
    if list_article:
        info_ozon = ozon_api.get_items(data=list_article)
        ozon_api.set_num_sku_id_ozon(info_ozon)


@shared_task
def ozon_create_order(num_order):
    try:
        ozon_api = OzonExchange()
        if not OrderOzon.objects.filter(number_ozon=num_order).exists():
            order_info = ozon_api.get_new_order(num_order)['result']
            number_to_ozon = order_info['posting_number']
            num = ozon_api.number_to_1c()
            new_order,created = OrderOzon.objects.update_or_create(number_1C=num, defaults={
                'number_ozon':number_to_ozon,
            })
            products_to_order = order_info['products']
            for prod in products_to_order:
                num = ozon_api.prod_in_catalog(prod['offer_id'])
                item = ItemInOrderOzon()
                item.order_num = new_order
                item.product = num
                item.form_price = TypePrices.objects.get(suffix='retail_price').uuid_1C
                item.price = float(prod['price'])
                item.quantity = prod['quantity']
                item.save()
            new_order.price = sum([i.total_price for i in new_order.items.all()])
            new_order.save()
        else:
            print(f'Заказ OZON {num_order} уже существует в системе')
        return True
    except:
        return False


@shared_task
def update_remains_ozon():
    print("start update remains OZON")
    ozon_api = OzonExchange()
    ozon_data = OzonData.objects.all().values_list('offer_id', 'ozon_id', 'product__stock')
    stock = []
    for item in ozon_data:
        if len(stock) > 99:
            ozon_api.update_remains(data=stock)
            stock.clear()
        item_stock_info =  {
                "offer_id": item[0],
                "stock": item[2] if ozon_api.work_time_ozon() else 0,
                "quant_size":1
            }
        item_stock_info.update(
                {
                    "warehouse_id": 22865154657000,
                    "product_id": item[1],
                }
            )
        stock.append(item_stock_info)
    if len(stock) > 0:
        ozon_api.update_remains(data=stock)
    print("end update remains OZON")


def ozon_update_file_article():
    ozon_artile = pd.read_excel('src/OzonData/update_vendor_code(1).xlsx')
    for index, row in ozon_artile.iterrows():
        value_from_a = row["Старый артикул"]  # Значение из столбца A
        try:
            prod = OzonData.objects.get(offer_id=value_from_a)
            ozon_artile.at[index, "Новый артикул"] = prod.product.code_1C
        except:
            pass
        # Вставляем результат в столбец B той же строки
    ozon_artile.to_excel("update_article_result.xlsx", index=False)


def ozon_update_attr():
    all_prod_in_ozon = Product.objects.filter(ozon__isnull=False)
    ozon_api = OzonExchange()
    data_update = []

    for product in all_prod_in_ozon:
        family = product.category.get_family()
        video_category = family.filter(video_instruction_url__isnull=False).first()

        if not video_category:
            continue

        video_url = video_category.video_instruction_url
        category_name = video_category.name.lower().strip()

        data_update.append({
            "attributes": [
                {
                    "complex_id": 100001,
                    "id": 21841,
                    "value": [{"value": video_url}]
                },
                {
                    "complex_id": 100001,
                    "id": 21837,
                    "values": [{"value": f'Инструкция {category_name}'}]
                }
            ],
            "offer_id": product.code_1C
        })

        # Отправка каждые 100 товаров
        if len(data_update) >= 100:
            ozon_api.post_update_attr(data=data_update, save_to_file=True)
            data_update.clear()

    # Финальная отправка оставшихся
    if data_update:
        ozon_api.post_update_attr(data=data_update, save_to_file=True)


def ozon_article():
    ozon_artile = pd.read_excel('update_article_result.xlsx')

    for index, row in ozon_artile.iterrows():
        new_article = str(row["Новый артикул"]).strip()
        OzonData.objects.update_or_create(product=Product.objects.get(code_1C=new_article),
                                          defaults={
                                              'offer_id':new_article
                                          }
                                          )



def update_img_ozon():
    ozon_api = OzonExchange()
    url = 'https://lpff.ru'
    products = Product.objects.filter(ozon__isnull=False)
    for p in products:
        all_images = [f'{url}{img.image.url}'for img in p.images.all().order_by('-main')]
        payload = {
            "images":all_images,
            "product_id":p.ozon.ozon_id
        }
        print(json.dumps(payload, ensure_ascii=False))
        ozon_api.post_new_img(data=payload)


def ozon_update_to_exele():
    OZON_CLASS_MAP = {
        "Пленка защитная для автомобиля": [OzonTapeOutSaloon, 971053255,17028755],
        "Пленка защитная для салона автомобиля": [OzonTapeInSaloon,971077309,17028749],
        "Стекло защитное для экрана авто": [OzonProtectGlass,970702708,17028749],
    }
    ozon_exchange = OzonExchange()
    df = pd.read_excel("DATA/InSaloon.xlsx")
    data_sent = []
    for _, row in df.iterrows():
        code = row[0]  # например, AA-00006395
        type_name = row[1]  # "Пленка защитная для автомобиля"
        try:
            product = Product.objects.get(code_1C=code)  # <-- тут логика поиска товара по коду
        except:
            pass
        ozon_item = OZON_CLASS_MAP.get(type_name)
        if not ozon_item:
            print(f"❌ Неизвестный тип товара: {type_name}")
            continue

        item = ozon_item[0](product, ozon_item[1], ozon_item[2])
        data_sent.append(item.item())
        if len(data_sent) >= 100:
            ozon_exchange.post_items(data_sent, save_to_file=True)
            data_sent.clear()
    if data_sent:
        ozon_exchange.post_items(data_sent, save_to_file=True)


