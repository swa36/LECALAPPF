from celery import shared_task
from order.models import OrderOzon
from src.lekala_class.class_1C.ExchangeOrder1CtoMarket import OrderMarketplaceTo1C

@shared_task
def order_change():
    # order_avito = OrderAvito.objects.filter(change_1C=False)
    order_ozon = OrderOzon.objects.filter(exchange_1c=False)
    # order_ali = OrderAli.objects.filter(exchange_1c=False)
    # order_wb = OrderWB.objects.filter(exchange_1c=False)
    order_list = [order_ozon]
    for orders in order_list:
        for order in orders:
            order_exchange = OrderMarketplaceTo1C(order)
            order_exchange.send_to_1c()