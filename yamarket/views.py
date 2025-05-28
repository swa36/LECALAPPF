from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
import json, datetime
from catalog.models import Product
from order.models import OrderYM, ItemInOrderYM
from src.lekala_class.class_marketplace.YaMarket import YaMarket
# Create your views here.

@csrf_exempt
def updateStock(request):
    if request.headers['Authorization'] == settings.TOKEN_YA_MARKET:
        data = json.loads(request.body.decode('utf-8'))
        stocks = data['skus']
        # log = open('yaMarket/stock.log', 'a+')
        # log.write(str(data) + '\n')
        stockForSent = []
        for s in stocks:
            num = YaMarketApi().prod_in_catalog(s)
            if num._meta.model_name == 'catalog':
                count = num.quantity.remains
            else:
                count = num.frame_in_article.quantity.remains
            stockForSent.append(
                {
                "sku": s,
                "warehouseId": 103795,
                "items": [{"count": count, "type": "FIT",}]
                }
            )
        return JsonResponse({"skus":stockForSent}, safe=False, status = 500)
        # headers = json.loads(request.headers.decode('utf-8'))
    return JsonResponse({'error':'Error'}, safe=False, status = 500)

@csrf_exempt
def newOrder(request):
    if request.headers['Authorization'] == settings.TOKEN_YA_MARKET:
        data = json.loads(request.body.decode('utf-8'))
        # log = open('logs/market.log', 'a+')
        # log.write(str(data) + '\n')
        orderData = data['order']
        if not OrderYM.objects.filter(number_ym=orderData['id']).exists():
            number_1C = YaMarket().number_to_1c()
            order, created = OrderYM.objects.update_or_create(number_ym=orderData['id'],
                                                     defaults={
                                                         'price':orderData['itemsTotal']
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
            
            return JsonResponse({"order": {"id": number_1C}}, status = 201)
        return JsonResponse({}, safe=False, status = 200)

@csrf_exempt
def statusOrder(request):
    if request.headers['Authorization'] == settings.TOKEN_YA_MARKET:
        data = json.loads(request.body.decode('utf-8'))
        # log = open('logs/status_market.log', 'a+')
        # log.write(str(data) + '\n')
        orderData = data['order']
        if OrderYM.objects.filter(number_1C=orderData['shopOrderId']).exists() or OrderYM.objects.filter(number_ym=orderData['shopOrderId']).exists():          
            return JsonResponse({}, safe=False, status = 200)
        return JsonResponse({'error':'Error'}, safe=False, status = 500)