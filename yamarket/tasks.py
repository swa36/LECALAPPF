from celery import shared_task
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