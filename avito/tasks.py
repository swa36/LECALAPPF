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
                raw_items = raw_order.get('items', [])
                order = OrderAvito.objects.create(
                    number_avito=order_id,
                    number_1C=avito.number_to_1c(),
                    name_advertisement=raw_items[0].get('title', '') if raw_items else '',
                )
                for raw_item in raw_items:
                    product = Product.objects.filter(code_1C=raw_item.get('id')).first()
                    quantity = raw_item.get('count', 1)
                    total = raw_item.get('prices', {}).get('total', 0)
                    ItemInOrderAvito.objects.create(
                        order_num=order,
                        product=product,
                        name_advertisement_item=raw_item.get('title', ''),
                        price=total,
                        quantity=quantity,
                    )
                order_total = raw_order.get('prices', {}).get('total')
                order.price = (
                    order_total
                    if order_total is not None
                    else sum(item.total_price for item in order.items.all())
                )
                order.save(update_fields=['price'])
                created += 1
        except Exception:
            logger.exception('Avito order import failed', extra={'order': raw_order})

    return {'created': created}
