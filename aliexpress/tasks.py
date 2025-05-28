from itertools import product

from celery import shared_task
from django.conf import settings
from catalog.models import Product
from src.lekala_class.class_marketplace.AliExpress import AliExpress
from src.lekala_class.class_feed import CreatorFeed
from order.models import OrderAli, ItemInOrderAli
from django.db.models import Q
from time import sleep

ali = AliExpress()



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
    products = Product.objects.filter(ozon__isnull=False).values_list('ozon__offer_id')
    list_article = []
    for item in products:
        if len(list_article) > 49:
            data = ali.get_item(data=list_article)['data']
            for i in data:
                if i['sku']:
                    article, id_ali = i['sku'][0]['code'], i['id']
                    ali.set_id_ali(article, id_ali)
            list_article.clear()
        if item[0]:
            list_article.append(item[0])
    if list_article:
        data = ali.get_item(data=list_article)['data']
        for i in data:
            if i['sku']:
                article, id_ali = i['sku'][0]['code'], i['id']
                ali.set_id_ali(article, id_ali)



@shared_task
def update_stock_ali():
    print('start updates stock ALI')
    catalog_stock = Catalog.objects.exclude(
        category__name__in=EXCLUDE_LIST).filter(Q(id_ali__isnull=False) | Q(id_ali_double__isnull=False),
                                                          price__retail_price__gt=500).values_list('id_ali',
                                                                                                   'id_ali_double',
                                                                                                   'article',
                                                                                                   'quantity__remains')
    frame_stock = Frame.objects.filter(Q(id_ali__isnull=False) | Q(id_ali_double__isnull=False)).values_list('id_ali',
                                                                                                             'id_ali_double',
                                                                                                             'model_frame',
                                                                                                             'frame_in_article__quantity__remains'
                                                                                                             )
    all_items = list(catalog_stock) + list(frame_stock)
    list_stock = []
    list_stock_double = []
    for item in all_items:
        if len(list_stock) > 999:
            ali.update_stock(data=list_stock)
            list_stock.clear()
            sleep(10)
        if len(list_stock_double) > 999:
            ali_double.update_stock(data=list_stock_double)
            list_stock_double.clear()
            sleep(10)
        article = str(item[2]).encode("ascii", "ignore").decode()
        dict_stock = {
            "product_id": '',
            "skus": [
                {
                    "sku_code": article,
                    "inventory": str(item[3])
                }
            ]
        }
        if item[0]:
            one = dict_stock.copy()
            one['product_id'] = item[0]
            list_stock.append(one)
        if item[1]:
            two = dict_stock.copy()
            two['product_id'] = item[1]
            list_stock_double.append(two)
    if list_stock:
        ali.update_stock(data=list_stock)
    if list_stock_double:
        ali_double.update_stock(data=list_stock_double)
    print('end updates stock ALI')


@shared_task
def get_order_ali():
    for ali_api in (ali, ali_double):
        order_info = ali_api.get_order()['data']['orders']
        if order_info:
            for o in order_info:
                if not OrderAli.objects.filter(number_ali=o['id']).exists():
                    number_1C_ALI = ali_api.number_to_1c(OrderAli.objects.last())
                    new_order, created = OrderAli.objects.get_or_create(number_ali=o['id'], number_1C=number_1C_ALI)
                    buyer_info = o['buyer_name'].split(' ')
                    family, name = buyer_info[0], buyer_info[1]
                    new_order.family = family
                    new_order.name = name
                    if not ali_api.double:
                        new_order.name_shop = 'AliExpress VDF-Light'
                    else:
                        new_order.name_shop = 'AliExpress VseDlyFar'
                    new_order.save()
                    if created:
                        for i in o['order_lines']:
                            item_ALI = ItemInOrderAli()
                            item_ALI.form_price = '3d04dfee-59ed-11e9-93d0-bcee7be013be'
                            item_ALI.product = ali.prod_in_catalog(i['sku_code'])
                            item_ALI.price = i['item_price']/100
                            item_ALI.quantity = int(i['quantity'])
                            item_ALI.total_price = i['total_amount']/100
                            item_ALI.order_num = new_order
                            item_ALI.save()
                        new_order.price = sum([i.total_price for i in new_order.number_order.all()])
                        new_order.save()

def delete_item():
    catalog_stock = Catalog.objects.exclude(
        category__name__in=EXCLUDE_LIST).filter(Q(id_ali__isnull=False) | Q(id_ali_double__isnull=False), price__retail_price__gt=500).values_list('id_ali', 'id_ali_double')
    frame_stock = Frame.objects.filter(Q(id_ali__isnull=False) | Q(id_ali_double__isnull=False)).values_list('id_ali', 'id_ali_double')
    list_id = list(catalog_stock) + list(frame_stock)
    list_delete = []
    list_delete_double = []
    for i in list_id:
        if len(list_delete) > 499:
            ali.delete_ali(data=list_delete)
            list_delete.clear()
        if len(list_delete_double) > 499:
            ali_double.delete_ali(data=list_delete_double)
            list_delete_double.clear()
        if i[0]:
            list_delete.append(i[0])
        if i[1]:
            list_delete_double.append(i[1])
    if list_delete:
        ali.delete_ali(data=list_delete)
    if list_delete_double:
        ali_double.delete_ali(data=list_delete_double)
