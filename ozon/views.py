from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from ozon.tasks import ozon_create_order
import json, datetime, os
from django.conf import settings

# Create your views here.

@csrf_exempt
def ozon_push(request):
    try:
        body = request.body.decode('utf-8')
        if not body:
            return JsonResponse({'error': 'Пустое тело запроса'}, status=400)
        data = json.loads(body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Невалидный JSON'}, status=400)

    # логируем
    log_path = os.path.join(settings.BASE_DIR, 'ozon', 'push.log')
    with open(log_path, 'a+', encoding='utf-8') as log:
        log.write(str(data) + '\n')

    message_type = data.get('message_type')

    if message_type == 'TYPE_PING':
        return JsonResponse({
            "version": "1",
            "name": "vdf",
            "time": datetime.datetime.now().isoformat(timespec='seconds') + 'Z'
        })

    elif message_type == 'TYPE_NEW_POSTING':
        number_ozon = data.get('posting_number')
        if not number_ozon:
            return JsonResponse({'error': 'Не указан posting_number'}, status=400)

        resp = ozon_create_order(number_ozon)
        if resp:
            return JsonResponse({"result": True})
        else:
            return JsonResponse({
                "error": {
                    "code": "ERROR_UNKNOWN",
                    "message": "ошибка",
                    "details": None
                }
            }, status=500)

    else:
        return JsonResponse({'error': f'Неизвестный message_type: {message_type}'}, status=400)


