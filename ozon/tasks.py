from celery import shared_task
import lekala_ppf.settings as settings
from catalog.models import Product, MarkUpItems, TypePrices
import pandas as pd
import json

from order.models import OrderOzon, ItemInOrderOzon
from ozon.models import OzonData
from src.lekala_class.class_marketplace.OzonExchange import OzonExchange
from pathlib import Path
from src.lekala_class.class_marketplace.OzonItem import OzonTape
from django.db.models import Q

def get_data_csv_ozon():
    filename = settings.BASE_DIR / 'src' / 'OzonData' / 'full_data_ozon.csv'
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


def add_new_item_ozon():
    ozon_api = OzonExchange()
    items = []
    products_not_ozon = Product.objects.filter(Q(ozon__isnull=True) & Q(stock__gt=0) & Q(images__isnull=False))
    for product in products_not_ozon:
        if len(items) > 99:
            ozon_api.post_items(data=items)
            items.clear()
        ozon_item = OzonTape(product)
        items.append(ozon_item.item())
    if len(items) > 0:
        ozon_api.post_items(data=items)


@shared_task
def update_price_ozon():
    ozon_api = OzonExchange()
    ozon_data = OzonData.objects.all().values('offer_id', 'product__prices__retail_price')
    mark_up = MarkUpItems.objects.last()
    data_price = []
    for item in ozon_data:
        item_price_info =  {
        "auto_action_enabled": "DISABLED",
        "price_strategy_enabled": "DISABLED",
        "min_price": str(item[1] + (mark_up.ozon_mark_up * item[1]) / 100),
        "offer_id": item[0],
        "old_price":"0",
        "price": str(item[1] + (mark_up.ozon_mark_up * item[1]) / 100),
        "vat":0
        }
        if len(data_price) > 999:
            ozon_api.update_price(data=data_price)
            data_price.clear()
        item_price_info.update({"product_id": item[1]})
        data_price.append(item_price_info)
    if data_price:
        ozon_api.update_price(data=data_price)


def set_ozon_prod_and_sku():
    ozon_api = OzonExchange()
    products_not_ozon = Product.objects.filter(Q(ozon__isnull=True) & Q(stock__gt=0) & Q(images__isnull=True)).values('code_1C')
    list_article = []
    for items in products_not_ozon:
        if len(list_article) > 999:
            info_ozon = ozon_api.get_items(data=list_article)
            ozon_api.set_num_sku_id_ozon(info_ozon)
            list_article.clear()
        if items[0]:
            list_article.append(items[0])
    if len(list_article) > 0:
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
        return True, num_order
    except:
        return False, num_order


@shared_task
def update_remains_ozon():
    print("start update remains OZON")
    ozon_api = OzonExchange()
    products_not_ozon = Product.objects.filter(Q(ozon__isnull=False)).values('ozon__offer_id', 'ozon__ozon_id', 'stock')
    stock = []
    for item in products_not_ozon:
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


