import logging

from celery import shared_task
from django.db import transaction

from catalog.models import Product
from order.models import ItemInOrderAvito, OrderAvito
from src.lekala_class.class_feed import CreatorFeed
from src.lekala_class.class_marketplace.Avito import AvitoExchange


logger = logging.getLogger(__name__)


@shared_task
def create_feed():
    avito_feed = CreatorFeed('avito')
    avito_feed.create_items()
    avito_feed.save()


@shared_task
def getOrderAvito():
    created = 0
    avito = AvitoExchange()
    try:
        orders = avito.get_order().get('orders', [])
    except Exception:
        logger.exception('Avito orders retrieval failed')
        return {'created': created}

    for raw_order in orders:
        try:
            order_id = str(raw_order.get('marketplaceId') or '')
            if not order_id or OrderAvito.objects.filter(number_avito=order_id).exists():
                continue

            with transaction.atomic():
                order = OrderAvito.objects.create(
                    number_avito=order_id,
                    number_1C=avito.number_to_1c(),
                )
                for raw_item in raw_order.get('items', []):
                    product = Product.objects.filter(code_1C=raw_item.get('id')).first()
                    ItemInOrderAvito.objects.create(
                        order_num=order,
                        product=product,
                        name_advertisement_item=raw_item.get('title', ''),
                        price=raw_item.get('prices', {}).get('price', 0),
                        quantity=raw_item.get('count', 1),
                    )
                order.price = sum(item.total_price for item in order.items.all())
                order.save(update_fields=['price'])
                created += 1
        except Exception:
            logger.exception('Avito order import failed', extra={'order': raw_order})

    return {'created': created}
