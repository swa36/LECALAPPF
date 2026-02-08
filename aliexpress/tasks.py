from itertools import product

from celery import shared_task
from django.conf import settings

from aliexpress.models import AliData
from catalog.models import Product
from src.lekala_class.class_marketplace.AliExpress import AliExpress
from src.lekala_class.class_feed import CreatorFeed
from order.models import OrderAli, ItemInOrderAli
from django.db.models import Q
from time import sleep

EXCLUDE_LIST = ['Архив',
                'Переходные рамки',
                'HPL',
                'SLC',
                '3008',
                'ГАЛОГЕННЫЕ ЛИНЗЫ',
                'ОРИГИНАЛЬНЫЕ ЛИНЗЫ']

@shared_task
def create_feed_ALI():
    feed_ali = CreatorFeed(name_market='ali')
    feed_ali.create_items()
    feed_ali.save()



@shared_task
def set_id_ali():
    ali = AliExpress()
    products = Product.objects.filter(ali__isnull=True).values_list('code_1C')
    list_article = []
    delete_list = []
    for item in products:
        if len(delete_list) > 19:
            ali.delete_ali(data=delete_list)
            delete_list.clear()
        if len(list_article) > 49:
            data = ali.get_item(data=list_article)['data']
            for i in data:
                if i['sku']:
                    article, id_ali = i['sku'][0]['code'], i['id']
                    id_ali = ali.set_id_ali(article, id_ali)
                    if id_ali:
                        delete_list.append(id_ali)
            list_article.clear()
        if item[0]:
            list_article.append(item[0])
    if list_article:
        data = ali.get_item(data=list_article)['data']
        for i in data:
            if i['sku']:
                article, id_ali = i['sku'][0]['code'], i['id']
                id_ali = ali.set_id_ali(article, id_ali)
                if id_ali:
                    delete_list.append(id_ali)
    if delete_list:
        ali.delete_ali(data=delete_list)
        delete_list.clear()



@shared_task
def update_stock_ali():
    ali = AliExpress()
    print('start updates stock ALI')
    porduct_ali = AliData.objects.all().values_list('id_ali', 'product__code_1C', 'product__stock')
    list_stock = []
    for item in porduct_ali:
        if len(list_stock) > 999:
            ali.update_stock(data=list_stock)
            list_stock.clear()
            sleep(50)
        article = str(item[1]).encode("ascii", "ignore").decode()
        dict_stock = {
            "product_id": '',
            "skus": [
                {
                    "sku_code": article,
                    "inventory": str(item[2])
                }
            ]
        }
        if item[0]:
            one = dict_stock.copy()
            one['product_id'] = item[0]
            list_stock.append(one)
    if list_stock:
        ali.update_stock(data=list_stock)
    print('end updates stock ALI')


@shared_task
def get_order_ali():
    ali = AliExpress()
    order_info = ali.get_order()['data']['orders']
    if order_info:
        for o in order_info:
            if not OrderAli.objects.filter(number_ali=o['id']).exists():
                number_1C_ALI = ali.number_to_1c()
                new_order, created = OrderAli.objects.get_or_create(number_ali=o['id'], number_1C=number_1C_ALI)
                buyer_info = o['buyer_name'].split(' ')
                family, name = buyer_info[0], buyer_info[1]
                new_order.family = family
                new_order.name = name
                new_order.name_shop = 'AliExpress'
                new_order.save()
                if created:
                    for i in o['order_lines']:
                        item_ALI = ItemInOrderAli()
                        item_ALI.product = Product.objects.get(code_1C=i['sku_code'])
                        item_ALI.price = i['item_price']/100
                        item_ALI.quantity = int(i['quantity'])
                        item_ALI.total_price = i['total_amount']/100
                        item_ALI.order_num = new_order
                        item_ALI.save()
                    new_order.price = sum([i.total_price for i in new_order.items.all()])
                    new_order.save()

def delete_item():
    ali = AliExpress()
    products = Product.objects.filter(ali__isnull=False)
    list_delete = []
    for i in products:
        if len(list_delete) > 399:
            print("Шлем")
            ali.delete_ali(data=list_delete)
            list_delete.clear()
        if hasattr(i, 'ali'):
            list_delete.append(i.ali.id_ali)
    if list_delete:
        print("Шлем")
        ali.delete_ali(data=list_delete)
