from typing import Optional, Dict
import pandas as pd
from celery import shared_task
from django.db.models import Q

from order.models import OrderWB
from src.lekala_class.class_marketplace.WB import WBItemCard, PriceItemWB, StockItemWB, GetOrderWB
from catalog.models import Product, MarkUpItems, Category
from src.lekala_class.class_marketplace.WBItem import WBItem


def exele_wb():
    df = pd.read_excel("src/WBData/wb_data.xlsx", sheet_name="Товары")
    artikuls = df[["Артикул продавца","Наименование", "Артикул WB","Баркод"]]
    records = artikuls.dropna().to_dict(orient="records")
    # Печатаем список
    s=0
    for i in records:
        try:
            p = Product.objects.get(name__contains=i['Наименование'])
            if not hasattr(p, 'wb'):
                print(i)
        except Product.DoesNotExist:
            s+=1
        except Product.MultipleObjectsReturned:
            try:
                p = Product.objects.get(article_1C=i['Артикул продавца'])
            except Product.DoesNotExist:
                print(f'{i['Наименование']} два')
    print(s)



def set_id_wb(next_cursor:Optional[Dict]=None) -> None:
    wb_api = WBItemCard()
    if next_cursor:
        data = wb_api.get_items(param='withoutImg',cursor=next_cursor)
    else:
        data = wb_api.get_items(param='withoutImg')
    wb_api.set_id_wb_num(data)
    if 'nmID' in  data['cursor'] and 'updatedAt' in data['cursor']:
        next_cursor = {
            "updatedAt": data['cursor']['updatedAt'],
            "nmID": data['cursor']['nmID'],
            "limit": 100
        }
        set_id_wb(next_cursor)


@shared_task
def update_price_wb():
    wb_api = PriceItemWB()
    product_wb = Product.objects.filter(wb__isnull=False).values_list('wb__wb_id', 'prices__retail_price')
    mark_up = MarkUpItems.objects.last()
    list_price = []
    list_discount_wb = []
    for i in product_wb:
        price = wb_api.round_to_nearest_10_custom(i[1] + (mark_up.wildberries_mark_up * i[1]) / 100)
        if price <= 0:
            continue
        if i[0]:
            list_price.append({"nmID": int(i[0]),"price": int(price), "discount": 10})
            list_discount_wb.append({"nmID": int(i[0]), "clubDiscount": 30})
        if len(list_price) > 999:
            wb_api.update_price(data=list_price)
            wb_api.set_price_club_wb(data=list_discount_wb)
            list_price.clear()
            list_discount_wb.clear()
    if list_price:
        wb_api.update_price(data=list_price)
        wb_api.set_price_club_wb(data=list_discount_wb)



@shared_task
def update_remains_wb():
    print("Start update stock WB")
    wb_api = StockItemWB()
    product_wb = Product.objects.filter(wb__isnull=False).values_list('wb__wb_barcode', 'stock')
    list_stock = []
    for i in product_wb:
        if len(list_stock) > 999:
            wb_api.update_remains(data=list_stock, save_to_file=False)
            list_stock.clear()
        if i[0]:
            list_stock.append({"sku": str(i[0]), "amount": int(i[1]) if wb_api.work_time_wb() else 0})
    if list_stock:
        wb_api.update_remains(data=list_stock, save_to_file=False)
    print("End update stock WB")

@shared_task
def get_new_order_wb():
    wb_api = GetOrderWB()
    wb_order = wb_api.get_new_order()
    for o in wb_order['orders']:
        if not OrderWB.objects.filter(number_WB=o['id']).exists():
            price = o['convertedPrice']/100
            try:
                prod = Product.objects.get(article_1C=o['article'])
            except:
                prod = None
            number_1c = wb_api.number_to_1c()
            OrderWB.objects.create(
                number_WB=o['id'],
                number_1C=number_1c,
                product=prod,
                price = price,
            )
            print('New order create WB')
    return

def add_new_item_wb():
    wb_api = WBItemCard()
    exclude_cat = Category.objects.get(name='Инструмент и оборудование для нанесения плёнок').get_family()
    product_not_wb = Product.objects.filter(Q(wb__isnull=True) & ~Q(category__id__in=[i.id for i in exclude_cat]))
    # Обработка всех элементов в одном цикле
    batch = []
    for item in product_not_wb:
        # Если пакет заполнен, отправляем его
        if len(batch) >= 99:
            wb_api.post_items(data=batch)
            batch.clear()  # Очистка пакета после отправки
        # Преобразование элемента в формат для API
        item_data = WBItem(item).dataItemCard()
        if item_data:
            batch.append(item_data)

    # Отправка оставшихся элементов, если они есть
    if batch:
        wb_api.post_items(data=batch)


def sent_img_wb():
    wb_api = WBItemCard()
    data = wb_api.get_items(param='withoutImg')
    for i in data ['cards']:
        try:
            prod = Product.objects.get(article_1C=i['vendorCode'])
            wb_api.post_img(prod)
        except:
            print(i['vendorCode'])