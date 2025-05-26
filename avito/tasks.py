from celery import shared_task
from django.conf import settings
from catalog.models import Product
from order.models import ItemInOrderAvito, OrderAvito
from src.lekala_class.class_feed import CreatorFeed
from src.lekala_class.class_marketplace.Avito import AvitoExchange


def create_feed():
    avito_feed = CreatorFeed("avito")
    avito_feed.create_items()
    avito_feed.save()


@shared_task
def getOrderAvito():
    avito = AvitoExchange(client_id='...', client_secret='...')  # передай реальные значения или через settings
    try:
        orders = avito.get_order().get('orders', [])
    except Exception as e:
        print(f'Ошибка при получении заказов с Avito: {e}')
        return

    for order in orders:
        num_avito = order['marketplaceId']
        new_order, created = OrderAvito.objects.get_or_create(number_avito=num_avito, defaults={
            'number_1C': avito.number_to_1c(),
        })

        if created:
            for item in order['items']:
                item_id = item.get('id')
                name_advertisement = item.get('title', '')
                price = item['prices']['price']
                quantity = item.get('count', 1)
                try:
                    product = Product.objects.get(code_1C=item_id) if item_id else None
                except:
                    product = None

                ItemInOrderAvito.objects.create(
                    name_advertisement_item=name_advertisement,
                    product=product,
                    quantity=quantity,
                    price=price,
                    order_num=new_order,
                )

            new_order.price = sum([float(i.total_price) for i in new_order.number_order.all()])
            new_order.save()

            print(f'✅ Новый заказ с Avito создан: {new_order.number_1C}')