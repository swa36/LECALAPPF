import logging
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from ozon.tasks import ozon_create_order
import json
import datetime
import os
from django.conf import settings

logger = logging.getLogger(__name__)  # Получаем логгер текущего модуля

@csrf_exempt
def ozon_push(request):
    try:
        body = request.body.decode('utf-8')
        if not body:
            logger.warning("Получен пустой запрос от OZON")
            return JsonResponse({'error': 'Пустое тело запроса'}, status=400)
        data = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON: {e}")
        return JsonResponse({'error': 'Невалидный JSON'}, status=400)

    # Сохраняем в файл push.log
    try:
        log_path = os.path.join(settings.BASE_DIR, 'ozon', 'push.log')
        with open(log_path, 'a+', encoding='utf-8') as log:
            log.write(f"{datetime.datetime.now().isoformat()} | {body}\n")
    except Exception as e:
        logger.error(f"Ошибка записи в push.log: {e}")

    message_type = data.get('message_type')
    logger.info(f"OZON message_type: {message_type}")

    if message_type == 'TYPE_PING':
        response = {
            "version": "1",
            "name": "vdf",
            "time": datetime.datetime.now().isoformat(timespec='seconds') + 'Z'
        }
        logger.info(f"Ответ на TYPE_PING: {response}")
        return JsonResponse(response)

    elif message_type == 'TYPE_NEW_POSTING':
        number_ozon = data.get('posting_number')
        if not number_ozon:
            logger.warning("Отсутствует posting_number")
            return JsonResponse({'error': 'Не указан posting_number'}, status=400)

        logger.info(f"Создание заказа по posting_number: {number_ozon}")
        try:
            resp = ozon_create_order(number_ozon)
        except Exception as e:
            logger.exception(f"Ошибка при создании заказа через ozon_create_order: {e}")
            return JsonResponse({'error': 'Внутренняя ошибка сервера'}, status=500)

        if resp:
            logger.info(f"Заказ успешно создан: {number_ozon}")
            return JsonResponse({"result": True})
        else:
            logger.error(f"Ошибка создания заказа для {number_ozon}")
            return JsonResponse({
                "error": {
                    "code": "ERROR_UNKNOWN",
                    "message": "ошибка",
                    "details": None
                }
            }, status=500)

    else:
        logger.warning(f"Неизвестный message_type: {message_type}")
        return JsonResponse({'error': f'Неизвестный message_type: {message_type}'}, status=400)