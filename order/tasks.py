from celery import shared_task
from order.models import OrderOzon, OrderWB, OrderYM, OrderAli
from src.lekala_class.class_1C.ExchangeOrder1CtoMarket import OrderMarketplaceTo1C
from wildberries.tasks import get_new_order_wb
from aliexpress.tasks import get_order_ali
@shared_task
def order_change():
    # order_avito = OrderAvito.objects.filter(change_1C=False)
    order_ozon = OrderOzon.objects.filter(exchange_1c=False)
    order_ali = OrderAli.objects.filter(exchange_1c=False)
    order_wb = OrderWB.objects.filter(exchange_1c=False)
    order_ya = OrderYM.objects.filter(exchange_1c=False)
    order_list = [order_ozon, order_wb, order_ya, order_ali]
    for orders in order_list:
        for order in orders:
            order_exchange = OrderMarketplaceTo1C(order)
            order_exchange.send_to_1c()
            
@shared_task
def get_all_new_order():
    get_new_order_wb.delay()
    get_order_ali.delay()
    