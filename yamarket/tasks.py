from celery import shared_task
from django.http import JsonResponse

from catalog.models import Product
from order.models import OrderYM, ItemInOrderYM
from src.lekala_class.class_marketplace.YaMarket import YaMarket

def post_item_ya():
    market = YaMarket()
    market.post_item_data()
    return

@shared_task
def sent_stock_ya():
    print('Start update sotck YM')
    market = YaMarket()
    market.sent_stock_market()
    print('End update sotck YM')
    return

def get_order_info_ya(order_id):
    market = YaMarket()
    orderData = market.get_order_info(order_id)
    try:
        if not OrderYM.objects.filter(number_ym=orderData['id']).exists():
            number_1C = market.number_to_1c()
            order, created = OrderYM.objects.update_or_create(number_ym=orderData['id'],
                                                              defaults={
                                                                  'price': orderData['itemsTotal']
                                                              })
            if created:
                order.number_1C = number_1C
                order.save()
            else:
                number_1C = order.number_1C
            items = orderData['items']
            for i in items:
                num = Product.objects.get(code_1C=i['offerId'])
                itemsOrder = ItemInOrderYM()
                itemsOrder.order_num = order
                itemsOrder.product = num
                itemsOrder.form_price = '3d04dfee-59ed-11e9-93d0-bcee7be013be'
                itemsOrder.price = float(i['priceBeforeDiscount'])
                itemsOrder.quantity = i['count']
                itemsOrder.save()
            return True
    except Exception as e:
        return False
