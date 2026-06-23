# Дизайн: параллелизация обмена каталогом 1С через Celery

**Дата:** 2026-06-23
**Статус:** утверждён к реализации (вариант A)
**Область:** `catalog/tasks.py`, `src/lekala_class/class_1C/GetData1C.py`,
`src/lekala_class/class_1C/ExChange1C.py`, `lekala_ppf/settings.py`, тесты.

---

## 1. Проблема

`get_data_1C()` сейчас работает **последовательно в один поток**:

- `get_data_chunck(...)` вызывается **синхронно** в цикле (не `.delay()`), поэтому
  «разбиение на 5 чанков» не даёт параллелизма;
- внутри `set_catalog_data_stock` для каждого изменённого товара **синхронно**
  вызывается `get_img` (HTTP к 1С + декод base64 + удаление папки + запись файлов).

Итог: полное время = сумма всех HTTP-чтений + всех скачиваний картинок + всех
записей в БД, строго по очереди. Ядра простаивают. Узкое место — I/O, а не CPU.

## 2. Цели и ограничения

**Цель:** конвейерная обработка в несколько параллельных «ручьёв», без простоя,
с устойчивостью к сбоям 1С.

**Жёсткие ограничения окружения:**

- Прод-воркер: **4 ядра / 6 ГБ ОЗУ**.
- 1С (scloud) — одна хостовая инстанция, безопасный потолок **~4 параллельных
  запроса**. Это и есть реальный потолок, больше потоков смысла не имеют.
- Брокер/бэкенд: Redis (`redis://localhost:6379/0`).

**Не-цели (YAGNI):**

- Не вводим eventlet/gevent: выигрыша нет (потолок 4 к 1С), а `eventlet`+`psycopg2`
  даёт баги без monkey-patch.
- Не трогаем отправку заказов `POST /order` (отдельная ветка, риск дублей при ретрае).
- Не параллелим саму пагинацию `products` (последовательное чтение ~36 страниц
  дёшево; усложнять не нужно).

## 3. Архитектура

### 3.1. Очереди

Две очереди, оба типа задач ходят в 1С:

- `catalog` — оркестрация и запись каталога (БД-операции + чтение `products`).
- `images` — скачивание/сохранение изображений товара (HTTP + диск + запись `Images`).

### 3.2. Воркер

**Один** prefork-воркер на оба очереди, конкуренция = числу ядер:

```
celery -A lekala_ppf worker -Q catalog,images -c 4 --prefetch-multiplier=1 -O fair
```

- `-c 4` → максимум 4 задачи одновременно → **физически не более 4 запросов к 1С**
  (потолок соблюдается самим пулом, отдельный rate-limit не нужен).
- `--prefetch-multiplier=1 -O fair` → длинные задачи-картинки не захватывают префетч,
  слоты делятся честно между `catalog` и `images`.
- 4 prefork-ребёнка × ~200–250 МБ (Django+requests) ≈ ~1 ГБ — в 6 ГБ с запасом.

### 3.3. Поток выполнения

```
get_data_1C() [очередь catalog] — дирижёр:
  1. set_name_attribute()      \
  2. set_type_price()           }  синхронно (справочники мелкие, нужны для FK)
  3. set_category_catalog()    /
  4. items = get_all_products()      (последовательная пагинация)
  5. chunks = split(items, CHUNK_SIZE=100)
  6. chord(
        group(process_catalog_chunk.s(chunk) for chunk in chunks)
     )( after_catalog_update.s() )

process_catalog_chunk(chunk) [очередь catalog]:
  GetData1C().set_catalog_data_stock(chunk, async_images=True)
    → пишет Product/Prices/ValueAdditionalAttributes
    → вместо self.get_img(uuid) ставит update_product_images.delay(str(uuid))

update_product_images(uuid) [очередь images]:
  ExChange1C().get_img(uuid)   (логика без изменений, теперь отдельная задача)

after_catalog_update(results) [очередь catalog] — callback chord:
  update_remains_ozon.delay()
  update_remains_wb.delay()
  update_stock_ali.delay()
```

Ключевое: обновление остатков на маркетплейсы запускается **после завершения всех
чанков** (через chord-callback), но **не ждёт картинок** — остатки берутся из
каталога, не из фото. Картинки докачиваются фоном независимо.

## 4. Политика ретраев (429 / 500)

HTTP-уровень, на сессии `ExChange1C` (`urllib3.util.retry.Retry`):

```python
Retry(
    total=2,                                  # 1 запрос + 2 повтора = max 3 попытки
    backoff_factor=1,                         # экспоненциальная пауза между повторами
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,          # уважать Retry-After при 429
)
```

Покрывает все GET-потоки: `products`, `categories`, `attributes`, `pricetypes`,
`orders-in-shipping`, `product-images`.

- На задаче `update_product_images` **дополнительный** celery-retry **не вводим** —
  единый источник правды по повторам на HTTP-уровне (избегаем двойной логики).
- `POST /order` **не ретраим** (риск дублирования заказа) — вне области этой задачи.

## 5. Изменения по файлам

### 5.1. `lekala_ppf/settings.py`
- `CELERY_TASK_ROUTES`:
  - `catalog.tasks.process_catalog_chunk` → `{"queue": "catalog"}`
  - `catalog.tasks.get_data_1C` → `{"queue": "catalog"}`
  - `catalog.tasks.after_catalog_update` → `{"queue": "catalog"}`
  - `catalog.tasks.update_product_images` → `{"queue": "images"}`
- `CELERY_TASK_ACKS_LATE = True`, `CELERY_WORKER_PREFETCH_MULTIPLIER = 1`
  (картинки идемпотентны: пере-выполнение безопасно — полная перезапись `Images`).
- `CATALOG_CHUNK_SIZE = 100` (константа размера чанка).

### 5.2. `src/lekala_class/class_1C/ExChange1C.py`
- Скорректировать **существующий** `Retry` в `__init__` по разделу 4: добавить `429`
  в `status_forcelist`, выставить `total=2`, добавить `respect_retry_after_header=True`
  (сейчас `total=3`, без `429` и без `Retry-After`).

### 5.3. `src/lekala_class/class_1C/GetData1C.py`
- `set_catalog_data_stock(self, data_catalog, async_images=False)`:
  - при `async_images=True` вместо `self.get_img(product.uuid_1C)` выполнять
    `from catalog.tasks import update_product_images;
     update_product_images.delay(str(product.uuid_1C))` (импорт внутри метода —
    избежать циклического импорта);
  - при `async_images=False` — прежнее синхронное поведение (для скриптов/ручных
    прогонов и тестов маппинга).

### 5.4. `catalog/tasks.py`
- `get_data_1C()` — дирижёр: справочники синхронно → `get_all_products()` →
  `chord(group(process_catalog_chunk.s(c)))(after_catalog_update.s())`.
- Новая `@shared_task process_catalog_chunk(chunk)` →
  `GetData1C().set_catalog_data_stock(chunk, async_images=True)`.
- Новая `@shared_task update_product_images(uuid)` → `ExChange1C().get_img(uuid)`.
- Новая `@shared_task after_catalog_update(results=None)` → три `update_*.delay()`.
- Удалить старую синхронную `get_data_chunck` (заменена на `process_catalog_chunk`).

## 6. Тестирование (TDD)

Юнит-тесты (mock, без celery-брокера; вызываем тело задач напрямую):

1. `set_catalog_data_stock(async_images=True)` **ставит** `update_product_images.delay`
   (мок) и **не** вызывает `get_img` напрямую; при `False` — наоборот.
2. `set_catalog_data_stock` ставит картинку только когда `should_refresh_details`
   (новый/изменённый `data_version`), и не ставит при неизменном.
3. `update_product_images(uuid)` дергает `ExChange1C.get_img(uuid)`.
4. `get_data_1C` вызывает справочники → `get_all_products` → формирует chord из
   N чанков (мокать `chord`/`group`/`.delay`, проверить число и содержимое чанков).
5. `after_catalog_update` дергает три `update_*` `.delay()`.
6. `ExChange1C` Retry: `status_forcelist` содержит 429 и 500, `total == 2`,
   `respect_retry_after_header is True`.

Существующие 25 тестов (контракт snake_case, POST /order) должны остаться зелёными.

## 7. Раскатка

1. Код + тесты (TDD), `manage.py test catalog order` зелёные.
2. Перезапустить воркер новой командой с `-Q catalog,images`.
3. Прогнать `c1_step4_full --script-args CONFIRM` (без push) — наблюдать заполнение
   очередей и нагрузку на 1С (≤4 в полёте).
4. Затем штатный запуск по расписанию (`django_celery_beat`).

## 8. Риски

| Риск | Митигизация |
|---|---|
| 1С отдаёт 429/блокировки при 4 потоках | потолок `-c 4`; ретраи 429/500 с backoff |
| Картинка падает и роняет товар | картинки вынесены в отдельную задачу, изолированы |
| chord-callback не сработает при сбое чанка | чанки идемпотентны (`update_or_create`), повторный запуск `get_data_1C` чинит |
| Память на 4 prefork-детях | ~1 ГБ из 6 ГБ — запас; следить при росте каталога |
| Postgres: соединения от 4 детей + web | в пределах дефолтного `max_connections` |
| Циклический импорт tasks ↔ GetData1C | импорт `update_product_images` внутри метода |

## 9. Definition of Done

- [ ] Retry 429/500 (total=2, Retry-After) на сессии `ExChange1C`.
- [ ] `get_data_1C` использует chord(group(chunks)) + callback маркетплейсов.
- [ ] Картинки вынесены в `update_product_images` на очередь `images`.
- [ ] Роутинг очередей и `CATALOG_CHUNK_SIZE` в settings.
- [ ] Новые тесты (раздел 6) + старые 25 зелёные.
- [ ] Команда воркера задокументирована (`-Q catalog,images -c 4 ...`).
