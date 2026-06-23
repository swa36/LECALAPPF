# Handoff: миграция интеграции 1С на HTTP-сервис `prokopov`

> **Кому:** агенту-исполнителю (Codex).
> **От:** аналитик (Claude). Я изучил кодовую базу, ТЗ, миграционный документ и
> OpenAPI-схему, подготовил спеку, план и тест-план. **Код не писал** — реализация за тобой.
>
> **Что читать первым:** этот файл → `1c-api-migration.md` → `1c-api-openapi.yaml`
> → `docs/1c-api-tz.md` (старое ТЗ). Этот handoff самодостаточен, но первоисточники
> разрешают спорные детали контракта.

---

## 1. Цель

В проекте уже есть рабочая интеграция с 1С через **прямой OData**
(`/odata/standard.odata/...`). 1С-разработчик выкатил **новый HTTP-сервис**
`prokopov` (расширение `WEB_API_Prokopov`) с «человеческими» путями
`/hs/prokopov/...`, snake_case-ответами, gzip и единым `POST /order`.

Нужно **переписать клиент сайта** под новый сервис, **сохранив публичные сигнатуры
методов**, которые дёргают celery-таски, и **покрыть всё тестами**.

Сервис уже развёрнут и проверен на живой базе (по словам 1С-разработчика, все
эндпоинты отвечают `200`, `POST /order` создаёт и проводит `ЗаказКлиента`).

---

## 2. Затрагиваемые файлы

| Файл | Роль | Что делаем |
|---|---|---|
| `src/lekala_class/class_1C/ExChange1C.py` | базовый HTTP-клиент 1С | **переписать** под HS-сервис |
| `src/lekala_class/class_1C/GetData1C.py` | загрузка каталога в БД сайта | **переписать** разбор полей на snake_case |
| `src/lekala_class/class_1C/ExchangeOrder1CtoMarket.py` | отправка заказов в 1С | **переписать** на один `POST /order` |
| `catalog/tasks.py` | celery-таски каталога | **поправить** вызовы (убрать `get_price`/`get_stock`) |
| `order/tasks.py` | celery-таска заказов | проверить (вероятно, без изменений) |
| `lekala_ppf/settings.py` | настройки | **добавить** `BASE_URL_1C_HS` |
| `catalog/tests.py`, `order/tests.py` | тесты | **написать** (см. раздел 7) |

Точки вызова (потребители публичного API классов) — менять их сигнатуры нельзя
без правки этих мест:

- `catalog/tasks.py`: `GetData1C().get_catalog()['value']`, `get_price()`,
  `get_stock()`, `set_name_attribute()`, `set_type_price()`,
  `set_category_catalog()`, `set_catalog_data_stock(chunk)`, `ExChange1C().get_img(uuid)`.
- `order/tasks.py`: `OrderMarketplaceTo1C(order).send_to_1c()`.
- `wildberries/tasks.py:172` и далее: `ExChange1C()` + `get_img` (вызов закомментирован).
- `GetData1C.get_quantity_in_order()` — публичный метод (резерв/остатки в отгрузке);
  потребителей в коде сейчас нет, но метод сохраняем рабочим.

---

## 3. Общие требования нового сервиса (важно)

1. **Базовый URL:** `http://<host>/<base>/hs/prokopov` (вместо `/odata/standard.odata/`).
   Корень сервиса — `prokopov`.
2. **Basic Auth** — без изменений (`LOGIN_1C` / `PASSWORD_1C`).
3. **gzip:** все ответы сжаты. Слать `Accept-Encoding: gzip`. В `requests`
   распаковка автоматическая — достаточно заголовка (он и так ставится по умолчанию,
   но задаём явно).
4. **Тело `POST /order` — строго UTF-8**, `Content-Type: application/json; charset=utf-8`,
   **ключи на кириллице** (`Покупатель`, `Товары`...). Иначе 1С вернёт `500`.
   → сериализовать вручную: `json.dumps(body, ensure_ascii=False).encode('utf-8')`,
   передавать как `data=...` с явным `Content-Type` (не `json=`, чтобы гарантировать UTF-8).
5. **Все ключи ответов — snake_case** (`ref_key`, `parent_key`, `article`, `price`...).
6. **Единый формат ошибки:** `{ "error": "...", "code": "MACHINE_CODE" }` с HTTP 400/404/500.
   Коды: `INVALID_UUID`, `MISSING_ITEMS`, `MISSING_BUYER`, `ITEM_NOT_FOUND`,
   `UNKNOWN_ENDPOINT`, `INTERNAL_ERROR`.

---

## 4. Спецификация эндпоинтов (старое → новое)

### 4.1. Каталог: `GET /products?page=&page_size=`
Заменяет 3 старых запроса: товары (2.1) + цены (2.5) + остатки (2.6).
Постраничный. **Цены и остаток встроены в каждый товар.**

Оболочка ответа: `{ total, page, page_size, pages, items: [...] }`.

Маппинг полей товара (старое OData → новое):

| OData | Новое (snake_case) | Куда на сайте |
|---|---|---|
| `Ref_Key` | `ref_key` | `Product.uuid_1C` |
| `Parent_Key` | `parent_key` | `Product.category` (по uuid) |
| `DataVersion` | `data_version` | `Product.data_version` |
| `Code` | `code` | `Product.code_1C` |
| `Артикул` | `article` | `Product.article_1C` (`.strip()`) |
| `Description` | `description` | `Product.name` (`.strip()`) |
| `Описание` | `description_text` | `Product.description` |
| `ФайлКартинки_Key` | `picture_file_key` | `Product.main_img_uuid` |
| `ДополнительныеРеквизиты[]` | `additional_attributes[]` | `ValueAdditionalAttributes` |
| `…Свойство_Key` | `additional_attributes[].property_key` | связь с `NameAdditionalAttributes` |
| `…Значение` | `additional_attributes[].value` | `value_attribute` |
| цены (см. 2.5) | `prices[]` = `{price_type_key, price_name, price}` | `Prices.*` |
| остаток (см. 2.6) | `in_stock` (готовое число) | `Product.stock` |

Логика, которая **исчезает**: расчёт остатка по `RecordType` (`Receipt`/`Expense`)
и выбор последней цены по `Period`. Теперь 1С отдаёт готовые `in_stock` и срез
последних цен. Сопоставление цены полю — по `price_type_key == TypePrices.uuid_1C`.
Остаток клампим: `max(in_stock, 0)`.

### 4.2. `GET /categories` → `{ value: [ {ref_key, parent_key, description} ] }`
Логика дерева по `parent_key`, корень `00000000-0000-0000-0000-000000000000` — без изменений.

### 4.3. `GET /attributes` → `{ value: [ {ref_key, description} ] }` (названия характеристик).

### 4.4. `GET /pricetypes` → `{ value: [ {ref_key, description} ] }` (виды цен).
Сопоставление наименование → suffix модели `TypePrices` (без изменений):
`Закупочная→cost_price`, `Оптовая→wholesale_price`, `Опт2→wholesale_price_2`,
`Опт3→wholesale_price_3`, `Розничная→retail_price`.

### 4.5. `GET /orders-in-shipping` → `{ value: [ {order_key, items:[{nomenclature_key, quantity}]} ] }`
Заменяет 2 старых запроса (состояния 2.7 + документ 2.8). Фильтр по статусу
«в процессе отгрузки» делает 1С. Поля `Состояние` больше нет, дополнительный запрос
документа заказа **не нужен**.

### 4.6. `GET /product-images/{uuid_товара}`
→ `{ nomenclature_key, images:[{file_uuid, is_main, data_base64}] }`.
Заменяет 3 старых запроса (список файлов 2.9 + base64 из двух хранилищ 2.10/2.11).
`is_main: true` — главное изображение. На некорректный UUID — `400 INVALID_UUID`.

### 4.7. `POST /order` (всё в одной транзакции)
Заменяет 4 POST (партнёр 3.1 + контрагент 3.2 + заказ 3.3 + проведение 3.4).
1С сама ищет/создаёт партнёра и контрагента по `Покупатель`, проставляет константы
шапки, создаёт и **сразу проводит** документ.

**Тело (ключи кириллицей, UTF-8):**

```json
{
  "Покупатель": "OZON 123456789",
  "Номер": "OZ00-123456789",
  "Комментарий": "OZON\n123456789",
  "СуммаДокумента": 1991,
  "Товары": [
    { "Номенклатура_Key": "<uuid>", "Количество": 1, "Цена": 1991 }
  ]
}
```

| Поле | Обяз. | Источник на сайте |
|---|---|---|
| `Покупатель` | да | `platform_info['name_template'](order)` |
| `Номер` | нет | `platform_info['number_1C'](order)` если есть |
| `Комментарий` | нет | `_generate_order_comment(...)` |
| `СуммаДокумента` | нет | `order.price` (число) |
| `Товары[].Номенклатура_Key` | да | `str(item.product.uuid_1C)` |
| `Товары[].Количество` | да | `quantity` |
| `Товары[].Цена` | да | `price` |

**Успех (`200`):** `{ "ref_key": "<uuid проведённого заказа>" }`.
Больше **не** слать обвязку шапки (`Организация_Key`, `Склад_Key`, `Соглашение_Key`,
`Валюта_Key`, `СтавкаНДС_Key`, `ВидЦены_Key`, `ЭтапыГрафикаОплаты` и т.п.) — 1С
проставляет сама. Отдельный `/Post()` **не вызывать**.

**Ошибки:** `400 MISSING_ITEMS` / `400 MISSING_BUYER` / `404 ITEM_NOT_FOUND`
(номер строки в `error`) / `500 INTERNAL_ERROR`.

---

## 5. План реализации (пошагово)

> Делать строго по TDD: сначала тест из раздела 7 (RED), затем минимальная
> реализация (GREEN), затем рефактор. Тесты гоняются на тестовой БД (см. раздел 6).

**Шаг 0. Настройки.** В `lekala_ppf/settings.py` после `BASE_URL_1C` добавить:
```python
BASE_URL_1C_HS = env(
    'BASE_URL_1C_HS',
    default=BASE_URL_1C.replace('/odata/standard.odata/', '/hs/prokopov/'),
)
```
В `lekala_ppf/.env` (gitignored) опционально прописать `BASE_URL_1C_HS=...` явно.

**Шаг 1. `ExChange1C` (базовый клиент).**
- `BASE_URL = settings.BASE_URL_1C_HS` (с завершающим `/`).
- В `__init__` оставить `requests.Session` + retry; добавить
  `self.session.headers.update({'Accept-Encoding': 'gzip'})`.
- `_make_request(method, endpoint, params=None, json_body=None)`:
  - `url = self.BASE_URL + endpoint`;
  - `self.session.request(method, url=url, params=params, auth=self.auth, timeout=10[, ...])`;
  - `raise_for_status()`; вернуть `response.json()`;
  - на `requests.exceptions.RequestException` — лог и `return {"value": []}`
    (как в текущем коде, чтобы таски не падали).
  - убрать параметр `$format` (он от OData).
- Новые/переписанные GET-методы:
  - `get_products(page=1, page_size=200)` → `_make_request('GET', 'products', params={'page':..,'page_size':..})`, вернуть страницу.
  - `get_all_products(page_size=200)` → пройти страницы от 1 до `pages`, собрать `items` в один список. Вернуть список (см. влияние на `catalog/tasks.py`, шаг 4).
  - `get_category()` → `'categories'`.
  - `get_name_additional_attributes()` → `'attributes'`.
  - `get_type_price()` → `'pricetypes'`.
  - `get_orders_in_shipping()` → `'orders-in-shipping'`.
  - `get_img(id_item)` → `_make_request('GET', f'product-images/{id_item}')`; далее
    логика удаления старых изображений и сохранения новых, но из новой структуры:
    `images[]` с `file_uuid`/`is_main`/`data_base64`. Имя файла: `main_<ts>.jpg`
    для `is_main`, иначе `<n>_<ts>.jpg`. Декодировать `data_base64` → байты.
    Сохранить `Images` (как сейчас). Сохранить триггеры на ozon/wb (`hasattr`).
- **Удалить** методы старого OData: `get_catalog` (заменён на `get_products`/`get_all_products`),
  `get_price`, `get_stock`, `get_additional_attributes`, `get_reserv_item`,
  `_fetch_image_base64`, `_save_to_json` (если больше не используется).

**Шаг 2. `GetData1C`.**
- `set_name_attribute()`: `i['ref_key']`, `i['description']`.
- `set_category_catalog()`: `i['ref_key']`, `i['parent_key']`, `i['description']`
  (4 уровня дерева — логику оставить).
- `set_type_price()`: `i['ref_key']`, `i['description']`.
- `get_quantity_in_order()`: переписать на один `get_orders_in_shipping()`:
  пройти `value[].items[]`, суммировать `quantity` по `nomenclature_key`.
  Убрать запрос `Document_ЗаказКлиента(...)` и фильтр `Состояние`.
- `set_catalog_data_stock(data_catalog)`: разбирать snake_case-товар:
  - `stock = max(int(item['in_stock']), 0)`;
  - `Product`: `uuid_1C=item['ref_key']`, `article_1C=item['article'].strip()`,
    `code_1C=item['code']`, `name=item['description'].strip()`,
    `description=item['description_text']`, `main_img_uuid=item.get('picture_file_key')`,
    `category=Category.objects.get(uuid_1C=item['parent_key'])`;
  - цены: для каждого `TypePrices` найти в `item['prices']` запись с
    `price_type_key == str(tp.uuid_1C)`, взять `price` (иначе 0) → `Prices`;
  - `data_version=item.get('data_version')`; при создании/смене версии —
    обновить доп. атрибуты (`property_key`/`value`) и вызвать `self.get_img(...)`.
- **Удалить** `_get_data_stocks_prices` (чтение `json/data_1C/*.json` больше не нужно).

**Шаг 3. `OrderMarketplaceTo1C`.**
- `BASE_URL = settings.BASE_URL_1C_HS`.
- Удалить `DEFAULT_VALUES`, `create_user_1C`, `prepare_order_data` (обвязку шапки),
  `_prepare_product_data` в текущем виде, `_get_current_datetime`, `_get_shipment_date`.
- Оставить `PLATFORM_MAPPING`, `_get_platform_info`, `_get_order_items`,
  `_generate_order_comment`.
- `send_to_1c(post=False)`: собрать тело по разделу 4.7, отправить
  `POST {BASE_URL}order` с UTF-8 (см. раздел 3 п.4). Разобрать ответ:
  `ref_key` → успех, выставить `self.order.exchange_1c = True; save()`.
  На ошибочный ответ (`code` в теле или HTTP≥400) — залогировать, вернуть `False`,
  **не** трогать `exchange_1c`. `/Post()` не вызывать.
- Класс не наследует `ExChange1C`; завести собственную `requests.Session`/`requests`
  с тем же UTF-8-подходом (или вынести общий хелпер — на твоё усмотрение, но
  тесты в разделе 7 мокают `requests.post`/сессию).

**Шаг 4. `catalog/tasks.py` → `get_data_1C()`.**
- Убрать `data1C.get_price()` и `data1C.get_stock()`.
- Заменить `data_catalog = data1C.get_catalog()['value']` на
  `data_catalog = data1C.get_all_products()`.
- Порядок: справочники (`set_name_attribute`, `set_type_price`,
  `set_category_catalog`) **до** разбиения на чанки и `set_catalog_data_stock`
  (нужны для FK-связей). Чанкинг и рассылка остатков в маркетплейсы — без изменений.

**Шаг 5. `order/tasks.py`.** Скорее всего без изменений (вызывает `send_to_1c()`).
Проверить, что ничего не зависит от удалённых методов.

---

## 6. Окружение и запуск тестов

- БД: PostgreSQL на `localhost:5432`, креды в `lekala_ppf/.env`. Пользователь
  имеет право `CREATEDB` (тестовая БД `test_lekalappf` создаётся успешно).
- **Миграций нет в репозитории** (`migrations/` в `.gitignore`). Они уже
  сгенерированы локально (`makemigrations catalog order ozon wildberries aliexpress
  avito yamarket`) — без них тестовая БД не собирается (ошибка
  `django_content_type не существует` из-за порядка `run-syncdb`). Если их нет —
  выполнить `makemigrations` с явным перечислением приложений.
- Запуск:
  ```bash
  .venv/Scripts/python.exe manage.py test catalog order --noinput
  ```
  (PowerShell/Windows; интерпретатор — `.venv/Scripts/python.exe`).
- Лайв-1С в тестах **не дёргать** — весь HTTP мокать (`unittest.mock`).
  Доп. библиотек для моков (`responses`, `requests-mock`) в `req.txt` нет —
  использовать `unittest.mock.patch`.

---

## 7. Тест-план (acceptance) — эталонный набор

Ниже готовый набор тестов под `catalog/tests.py`. Это **спека в исполняемом виде**:
реализация считается принятой, когда все они зелёные. (Тесты для
`OrderMarketplaceTo1C` — в `order/tests.py`, по аналогии: мок `requests.post`,
проверка пути `…/order`, кириллических ключей тела, UTF-8-сериализации,
разбора `ref_key`, поведения при ошибке.)

```python
# catalog/tests.py
import base64
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from catalog.models import (
    Category, NameAdditionalAttributes, Prices, Product, TypePrices,
    ValueAdditionalAttributes,
)
from src.lekala_class.class_1C.ExChange1C import ExChange1C
from src.lekala_class.class_1C.GetData1C import GetData1C


def fake_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = json_data

    def raise_for_status():
        if status >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"{status}")

    resp.raise_for_status.side_effect = raise_for_status
    return resp


ONE_PX_PNG = base64.b64encode(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)).decode()


class ExChange1CHttpClientTest(TestCase):
    def setUp(self):
        self.client = ExChange1C()

    def test_base_url_points_to_http_service(self):
        self.assertTrue(self.client.BASE_URL.rstrip("/").endswith("/hs/prokopov"))

    def test_make_request_builds_url_and_sends_gzip_header(self):
        with patch.object(self.client.session, "request") as req:
            req.return_value = fake_response({"value": []})
            self.client._make_request("GET", "categories")
        args, kwargs = req.call_args
        called_url = kwargs.get("url") or args[1]
        self.assertTrue(called_url.endswith("/hs/prokopov/categories"))
        headers = {**self.client.session.headers, **(kwargs.get("headers") or {})}
        self.assertIn("gzip", headers.get("Accept-Encoding", "").lower())
        self.assertIsNotNone(kwargs.get("auth"))

    def test_make_request_returns_parsed_json(self):
        with patch.object(self.client.session, "request") as req:
            req.return_value = fake_response({"value": [{"ref_key": "a"}]})
            data = self.client._make_request("GET", "categories")
        self.assertEqual(data, {"value": [{"ref_key": "a"}]})

    def test_make_request_handles_network_error_gracefully(self):
        import requests
        with patch.object(self.client.session, "request",
                          side_effect=requests.exceptions.ConnectionError("boom")):
            data = self.client._make_request("GET", "categories")
        self.assertEqual(data, {"value": []})


class ExChange1CCatalogEndpointsTest(TestCase):
    def setUp(self):
        self.client = ExChange1C()

    def test_get_products_uses_pagination_params(self):
        page = {"total": 1, "page": 2, "page_size": 10, "pages": 1, "items": []}
        with patch.object(self.client, "_make_request", return_value=page) as mr:
            result = self.client.get_products(page=2, page_size=10)
        self.assertEqual(result, page)
        _, kwargs = mr.call_args
        params = kwargs.get("params") or {}
        self.assertEqual(params.get("page"), 2)
        self.assertEqual(params.get("page_size"), 10)

    def test_get_all_products_iterates_all_pages(self):
        pages = [
            {"total": 3, "page": 1, "page_size": 2, "pages": 2,
             "items": [{"ref_key": "1"}, {"ref_key": "2"}]},
            {"total": 3, "page": 2, "page_size": 2, "pages": 2,
             "items": [{"ref_key": "3"}]},
        ]
        with patch.object(self.client, "get_products", side_effect=pages) as gp:
            items = self.client.get_all_products(page_size=2)
        self.assertEqual([i["ref_key"] for i in items], ["1", "2", "3"])
        self.assertEqual(gp.call_count, 2)

    def test_get_category_calls_categories_endpoint(self):
        with patch.object(self.client, "_make_request", return_value={"value": []}) as mr:
            self.client.get_category()
        self.assertEqual(mr.call_args[0][1], "categories")

    def test_get_name_additional_attributes_calls_attributes_endpoint(self):
        with patch.object(self.client, "_make_request", return_value={"value": []}) as mr:
            self.client.get_name_additional_attributes()
        self.assertEqual(mr.call_args[0][1], "attributes")

    def test_get_type_price_calls_pricetypes_endpoint(self):
        with patch.object(self.client, "_make_request", return_value={"value": []}) as mr:
            self.client.get_type_price()
        self.assertEqual(mr.call_args[0][1], "pricetypes")

    def test_get_orders_in_shipping_calls_endpoint(self):
        with patch.object(self.client, "_make_request", return_value={"value": []}) as mr:
            self.client.get_orders_in_shipping()
        self.assertEqual(mr.call_args[0][1], "orders-in-shipping")


@override_settings(MEDIA_ROOT="/tmp/lekala_test_media")
class ExChange1CImagesTest(TestCase):
    def setUp(self):
        self.client = ExChange1C()
        self.cat = Category.objects.create(
            uuid_1C="11111111-1111-1111-1111-111111111111", name="Cat")
        self.product = Product.objects.create(
            uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d",
            main_img_uuid="f5a159fc-a7fb-11ef-8a72-00155d46f78d",
            article_1C="ART1", code_1C="CODE1", data_version="v1",
            name="Товар", description="opis", stock=1, category=self.cat)

    def test_get_img_requests_product_images_endpoint(self):
        with patch.object(self.client, "_make_request",
                          return_value={"nomenclature_key": str(self.product.uuid_1C),
                                        "images": []}) as mr:
            self.client.get_img(self.product.uuid_1C)
        self.assertEqual(mr.call_args[0][1],
                         f"product-images/{self.product.uuid_1C}")

    def test_get_img_saves_images_with_main_flag(self):
        payload = {"nomenclature_key": str(self.product.uuid_1C), "images": [
            {"file_uuid": "f5a159fc-a7fb-11ef-8a72-00155d46f78d",
             "is_main": True, "data_base64": ONE_PX_PNG},
            {"file_uuid": "00000000-0000-0000-0000-0000000000ab",
             "is_main": False, "data_base64": ONE_PX_PNG},
        ]}
        with patch.object(self.client, "_make_request", return_value=payload):
            self.client.get_img(self.product.uuid_1C)
        imgs = self.product.images.all()
        self.assertEqual(imgs.count(), 2)
        self.assertEqual(imgs.filter(main=True).count(), 1)
        self.assertTrue(imgs.get(main=True).filename.startswith("main_"))


class GetData1CAttributesTest(TestCase):
    def setUp(self):
        self.data = GetData1C()

    def test_set_name_attribute_reads_snake_case(self):
        payload = {"value": [{"ref_key": "13d974fe-ef5b-11ee-9903-00155d46f78c",
                              "description": "Материал"}]}
        with patch.object(self.data, "get_name_additional_attributes",
                          return_value=payload):
            self.data.set_name_attribute()
        obj = NameAdditionalAttributes.objects.get(
            uuid_1C="13d974fe-ef5b-11ee-9903-00155d46f78c")
        self.assertEqual(obj.name_attribute, "Материал")

    def test_set_type_price_reads_snake_case(self):
        payload = {"value": [{"ref_key": "e57af511-4c46-11ec-a9c8-f8cab8387a55",
                              "description": "Розничная"}]}
        with patch.object(self.data, "get_type_price", return_value=payload):
            self.data.set_type_price()
        obj = TypePrices.objects.get(uuid_1C="e57af511-4c46-11ec-a9c8-f8cab8387a55")
        self.assertEqual(obj.type_price, "Розничная")
        self.assertEqual(obj.suffix, "retail_price")


class GetData1CCategoriesTest(TestCase):
    def setUp(self):
        self.data = GetData1C()

    def test_set_category_catalog_builds_tree_snake_case(self):
        root = "e19fd7c4-0000-0000-0000-000000000001"
        child = "e19fd7c4-0000-0000-0000-000000000002"
        payload = {"value": [
            {"ref_key": root, "parent_key": "00000000-0000-0000-0000-000000000000",
             "description": "SUZUKI"},
            {"ref_key": child, "parent_key": root, "description": "SX4"},
        ]}
        with patch.object(self.data, "get_category", return_value=payload):
            self.data.set_category_catalog()
        root_obj = Category.objects.get(uuid_1C=root)
        child_obj = Category.objects.get(uuid_1C=child)
        self.assertEqual(root_obj.name, "SUZUKI")
        self.assertIsNone(root_obj.parent)
        self.assertEqual(child_obj.parent_id, root_obj.id)


class GetData1COrdersInShippingTest(TestCase):
    def setUp(self):
        self.data = GetData1C()

    def test_get_quantity_in_order_sums_from_single_endpoint(self):
        payload = {"value": [
            {"order_key": "order-1", "items": [
                {"nomenclature_key": "A", "quantity": 2},
                {"nomenclature_key": "B", "quantity": 1}]},
            {"order_key": "order-2", "items": [
                {"nomenclature_key": "A", "quantity": 3}]},
        ]}
        with patch.object(self.data, "get_orders_in_shipping", return_value=payload):
            result = self.data.get_quantity_in_order()
        self.assertEqual(result, {"A": 5, "B": 1})

    def test_get_quantity_in_order_handles_empty(self):
        with patch.object(self.data, "get_orders_in_shipping",
                          return_value={"value": []}):
            self.assertEqual(self.data.get_quantity_in_order(), {})


class GetData1CCatalogStockTest(TestCase):
    def setUp(self):
        self.data = GetData1C()
        self.cat = Category.objects.create(
            uuid_1C="ab1b2aba-a0c8-11ee-8400-00155d46f78d", name="Категория")
        NameAdditionalAttributes.objects.create(
            uuid_1C="13d974fe-ef5b-11ee-9903-00155d46f78c", name_attribute="Материал")
        TypePrices.objects.create(
            uuid_1C="e57af511-4c46-11ec-a9c8-f8cab8387a55",
            type_price="Розничная", suffix="retail_price")
        TypePrices.objects.create(
            uuid_1C="e57af510-4c46-11ec-a9c8-f8cab8387a55",
            type_price="Закупочная", suffix="cost_price")

    def _item(self):
        return {
            "ref_key": "7e019266-24a4-11ef-8009-00155d46f78d",
            "data_version": "AAAAAAAEW/Q=",
            "parent_key": "ab1b2aba-a0c8-11ee-8400-00155d46f78d",
            "is_folder": False, "code": "AA-00002351", "article": "MEC18Z ",
            "weight_numerator": 0.3, "description": "Плёнка для зеркал ",
            "description_text": "Описание плёнки",
            "picture_file_key": "f5a159fc-a7fb-11ef-8a72-00155d46f78d",
            "additional_attributes": [
                {"property_key": "13d974fe-ef5b-11ee-9903-00155d46f78c",
                 "description": "Материал", "value": "Полиуретан"}],
            "prices": [
                {"price_type_key": "e57af510-4c46-11ec-a9c8-f8cab8387a55",
                 "price_name": "Закупочная", "price": 650},
                {"price_type_key": "e57af511-4c46-11ec-a9c8-f8cab8387a55",
                 "price_name": "Розничная", "price": 1991}],
            "in_stock": 46,
        }

    def test_creates_product_with_embedded_stock_and_prices(self):
        with patch.object(self.data, "get_img"):
            self.data.set_catalog_data_stock([self._item()])
        product = Product.objects.get(uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d")
        self.assertEqual(product.article_1C, "MEC18Z")
        self.assertEqual(product.code_1C, "AA-00002351")
        self.assertEqual(product.name, "Плёнка для зеркал")
        self.assertEqual(product.description, "Описание плёнки")
        self.assertEqual(product.stock, 46)
        self.assertEqual(str(product.main_img_uuid),
                         "f5a159fc-a7fb-11ef-8a72-00155d46f78d")
        self.assertEqual(product.category_id, self.cat.id)
        prices = Prices.objects.get(product=product)
        self.assertEqual(int(prices.retail_price), 1991)
        self.assertEqual(int(prices.cost_price), 650)
        self.assertEqual(
            ValueAdditionalAttributes.objects.get(product=product).value_attribute,
            "Полиуретан")

    def test_negative_stock_is_clamped_to_zero(self):
        item = self._item(); item["in_stock"] = -5
        with patch.object(self.data, "get_img"):
            self.data.set_catalog_data_stock([item])
        self.assertEqual(
            Product.objects.get(uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d").stock, 0)

    def test_missing_price_type_defaults_to_zero(self):
        item = self._item()
        item["prices"] = [{"price_type_key": "e57af511-4c46-11ec-a9c8-f8cab8387a55",
                           "price_name": "Розничная", "price": 1991}]
        with patch.object(self.data, "get_img"):
            self.data.set_catalog_data_stock([item])
        prices = Prices.objects.get(
            product__uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d")
        self.assertEqual(int(prices.retail_price), 1991)
        self.assertEqual(int(prices.cost_price), 0)
```

Тесты для заказа (`order/tests.py`) — реализовать аналогично; обязательные кейсы:
1. `send_to_1c()` шлёт `POST` на `…/hs/prokopov/order`.
2. Тело содержит кириллические ключи `Покупатель`/`Товары` и сериализовано в UTF-8
   (проверить, что в отправленных байтах присутствует, например, `Покупатель`
   в UTF-8, т.е. `ensure_ascii=False`).
3. Состав `Товары[]` = `{Номенклатура_Key, Количество, Цена}` из строк заказа.
4. Успешный ответ `{ "ref_key": ... }` → `order.exchange_1c == True`.
5. Ответ с ошибкой (`code`/HTTP≥400) → `send_to_1c()` вернул `False`,
   `exchange_1c` не изменён, `/Post()` не вызывался.

---

## 8. Открытые вопросы / риски

1. **Формат `СуммаДокумента`** — слать числом (в примерах OpenAPI `number`).
   Текущий код слал строкой `str(order.price)`. В новом теле — число.
2. **`Покупатель` для Avito** — у `orderavito` нет `number_1C` в `PLATFORM_MAPPING`,
   но `order_change()` его и не обрабатывает. `number_1C` дёргать опционально
   (`.get('number_1C')`).
3. **gzip в моках** — тесты не проверяют реальную распаковку (её делает `requests`);
   проверяется только наличие заголовка. Для smoke-проверки на живой базе —
   отдельно, вручную (не в CI).
4. **Идемпотентность `POST /order`** — 1С сама ищет/создаёт партнёра; повторная
   отправка того же заказа создаст дубль. Защита — флаг `exchange_1c` (как сейчас).
5. **Поля `id_patner`/`id_contr`** в моделях заказов больше не заполняются
   (партнёр/контрагент создаются внутри 1С). Поля оставить (миграцию не трогаем),
   просто не писать в них.
6. **Миграции** не в репозитории — это существующее состояние проекта, в рамках
   задачи не чиним. Только держим в курсе для запуска тестов.

---

## 9. Definition of Done

- [ ] `BASE_URL_1C_HS` добавлен в настройки.
- [ ] `ExChange1C` ходит в `/hs/prokopov/*`, gzip-заголовок, snake_case, без `$format`.
- [ ] `get_products`/`get_all_products` с пагинацией; старые OData-методы удалены.
- [ ] `GetData1C` разбирает snake_case + встроенные `prices[]`/`in_stock`;
      `get_quantity_in_order` — через `/orders-in-shipping`.
- [ ] `get_img` — через `/product-images/{uuid}`, оба хранилища больше не различаются.
- [ ] `OrderMarketplaceTo1C.send_to_1c` — один `POST /order`, UTF-8, кириллица,
      без обвязки шапки и без `/Post()`.
- [ ] `catalog/tasks.py`/`order/tasks.py` поправлены под новые сигнатуры.
- [ ] Тесты из раздела 7 (+ заказ) зелёные:
      `manage.py test catalog order --noinput`.
- [ ] `manage.py check` без ошибок.
```
