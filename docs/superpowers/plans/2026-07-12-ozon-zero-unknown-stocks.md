# Обнуление остатков Ozon для карточек вне базы — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Спека:** `docs/superpowers/specs/2026-07-12-ozon-zero-unknown-stocks-design.md`

**Goal:** После каждого прогона `update_remains_ozon` карточки на Ozon, отсутствующие в локальной `OzonData`, получают `stock: 0` и закрываются для продажи.

**Architecture:** Новый метод `OzonExchange.get_product_list()` (`POST /v3/product/list`, пагинация по `last_id`) + новая функция `close_unknown_ozon_stocks(dry_run=False)` в `ozon/tasks.py`, которая сравнивает offer_id с Ozon с `OzonData` и шлёт `stock: 0` батчами по 100 через существующий `update_remains()` (`POST /v2/products/stocks`). Вызывается в конце Celery-задачи `update_remains_ozon` в try/except.

**Tech Stack:** Django, Celery, unittest.mock; тесты — `python manage.py test ozon`.

## Global Constraints

- `warehouse_id` FBS-склада: `22865154657000` (тот же, что в текущем `update_remains_ozon`).
- Батч `POST /v2/products/stocks`: максимум 100 позиций; лимит Ozon — 80 запросов/мин.
- `POST /v3/product/list`: `limit` максимум 1000; первый запрос с `last_id=""`, конец пагинации — пустой `items` или пустой `last_id`.
- Логирование через `print()` — так принято во всём `ozon/tasks.py`, не вводить logging.
- В dev-среде база неактуальна: реальные запросы к API из dev не делать, только тесты с моками (боевой первый запуск — см. Task 3, шаг «прод»).
- Кодировка файлов UTF-8, комментарии и docstring на русском (как в существующем коде).

---

### Task 1: `OzonExchange.get_product_list()`

**Files:**
- Modify: `src/lekala_class/class_marketplace/OzonExchange.py` (после метода `get_items`, ~строка 44)
- Test: `ozon/tests.py`

**Interfaces:**
- Consumes: `BaseMarketPlace._request(method, endpoint, data=...)` — уже существует, шлёт HTTP-запрос и возвращает распарсенный JSON-ответ.
- Produces: `OzonExchange.get_product_list(last_id="", limit=1000) -> dict` — сырой ответ Ozon вида `{"result": {"items": [{"offer_id": str, "product_id": int, "archived": bool, ...}], "last_id": str, "total": int}}`. Одна страница за вызов; пагинацию крутит вызывающий код.

- [ ] **Step 1: Написать падающий тест**

Заменить содержимое `ozon/tests.py` на:

```python
from unittest.mock import patch

from django.test import TestCase


class GetProductListTest(TestCase):
    @patch("src.lekala_class.class_marketplace.OzonExchange.OzonExchange._request")
    def test_get_product_list_calls_v3_product_list(self, mock_request):
        from src.lekala_class.class_marketplace.OzonExchange import OzonExchange

        mock_request.return_value = {"result": {"items": [], "last_id": "", "total": 0}}
        api = OzonExchange()
        res = api.get_product_list(last_id="abc", limit=500)

        mock_request.assert_called_once_with(
            "POST",
            "v3/product/list",
            data={
                "filter": {"visibility": "ALL"},
                "last_id": "abc",
                "limit": 500,
            },
        )
        self.assertEqual(res, {"result": {"items": [], "last_id": "", "total": 0}})
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `python manage.py test ozon.tests.GetProductListTest -v 2`
Expected: FAIL/ERROR с `AttributeError: ... has no attribute 'get_product_list'`

- [ ] **Step 3: Реализация**

В `src/lekala_class/class_marketplace/OzonExchange.py` после метода `get_items` добавить:

```python
    def get_product_list(self, last_id="", limit=1000):
        """Одна страница списка всех карточек продавца (/v3/product/list)."""
        endpoint = 'v3/product/list'
        payload = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": limit,
        }
        return self._request('POST', endpoint, data=payload)
```

- [ ] **Step 4: Убедиться, что тест проходит**

Run: `python manage.py test ozon.tests.GetProductListTest -v 2`
Expected: PASS (1 тест OK)

- [ ] **Step 5: Commit**

```bash
git add src/lekala_class/class_marketplace/OzonExchange.py ozon/tests.py
git commit -m "feat(ozon): метод get_product_list для /v3/product/list"
```

---

### Task 2: `close_unknown_ozon_stocks()`

**Files:**
- Modify: `ozon/tasks.py` (новые функции после `update_remains_ozon`, ~строка 269)
- Test: `ozon/tests.py`

**Interfaces:**
- Consumes: `OzonExchange.get_product_list(last_id="", limit=1000) -> dict` (Task 1); `OzonExchange.update_remains(data=list) -> dict` — существующий метод, шлёт `{"stocks": data}` в `/v2/products/stocks`, возвращает `{"result": [{"offer_id": str, "updated": bool, "errors": []}, ...]}`; модель `ozon.models.OzonData` с полем `offer_id`.
- Produces: `close_unknown_ozon_stocks(dry_run=False) -> list[str]` — возвращает отсортированный список offer_id, которые были (или при dry_run — были бы) обнулены. Константа `OZON_WAREHOUSE_ID = 22865154657000` в `ozon/tasks.py`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `ozon/tests.py` (импорты дополнить, класс — в конец файла):

```python
import uuid

from catalog.models import Product
from ozon.models import OzonData


def make_ozon_product(code):
    """Товар + запись OzonData с offer_id=code."""
    product = Product.objects.create(
        uuid_1C=uuid.uuid4(),
        article_1C=code,
        code_1C=code,
        data_version="v1",
        name=f"Товар {code}",
        description="",
        stock=5,
    )
    OzonData.objects.create(product=product, offer_id=code)
    return product


def page(items, last_id=""):
    """Ответ /v3/product/list с одной страницей."""
    return {"result": {"items": items, "last_id": last_id, "total": len(items)}}


class CloseUnknownOzonStocksTest(TestCase):
    def _run(self, mock_api_cls, dry_run=False):
        from ozon.tasks import close_unknown_ozon_stocks
        with patch("ozon.tasks.time.sleep"):
            return close_unknown_ozon_stocks(dry_run=dry_run)

    @patch("ozon.tasks.OzonExchange")
    def test_zeroes_only_unknown_offer_ids(self, mock_api_cls):
        make_ozon_product("KNOWN-1")
        api = mock_api_cls.return_value
        api.get_product_list.return_value = page([
            {"offer_id": "KNOWN-1", "product_id": 1, "archived": False},
            {"offer_id": "UNKNOWN-1", "product_id": 2, "archived": False},
        ])
        api.update_remains.return_value = {"result": []}

        result = self._run(mock_api_cls)

        self.assertEqual(result, ["UNKNOWN-1"])
        api.update_remains.assert_called_once_with(data=[{
            "offer_id": "UNKNOWN-1",
            "stock": 0,
            "warehouse_id": 22865154657000,
            "quant_size": 1,
        }])

    @patch("ozon.tasks.OzonExchange")
    def test_pagination_and_archived_skipped(self, mock_api_cls):
        api = mock_api_cls.return_value
        api.get_product_list.side_effect = [
            page([{"offer_id": "A-1", "product_id": 1, "archived": False}], last_id="next"),
            page([
                {"offer_id": "A-2", "product_id": 2, "archived": True},
                {"offer_id": "A-3", "product_id": 3, "archived": False},
            ]),
        ]
        api.update_remains.return_value = {"result": []}

        result = self._run(mock_api_cls)

        self.assertEqual(result, ["A-1", "A-3"])  # A-2 архивная — пропущена
        self.assertEqual(api.get_product_list.call_count, 2)

    @patch("ozon.tasks.OzonExchange")
    def test_batching_by_100(self, mock_api_cls):
        api = mock_api_cls.return_value
        items = [
            {"offer_id": f"U-{i:03d}", "product_id": i, "archived": False}
            for i in range(250)
        ]
        api.get_product_list.return_value = page(items)
        api.update_remains.return_value = {"result": []}

        result = self._run(mock_api_cls)

        self.assertEqual(len(result), 250)
        self.assertEqual(api.update_remains.call_count, 3)
        sizes = [len(c.kwargs["data"]) for c in api.update_remains.call_args_list]
        self.assertEqual(sizes, [100, 100, 50])
        for call in api.update_remains.call_args_list:
            for item in call.kwargs["data"]:
                self.assertEqual(item["stock"], 0)

    @patch("ozon.tasks.OzonExchange")
    def test_dry_run_sends_nothing(self, mock_api_cls):
        api = mock_api_cls.return_value
        api.get_product_list.return_value = page(
            [{"offer_id": "UNKNOWN-1", "product_id": 1, "archived": False}]
        )

        result = self._run(mock_api_cls, dry_run=True)

        self.assertEqual(result, ["UNKNOWN-1"])
        api.update_remains.assert_not_called()

    @patch("ozon.tasks.OzonExchange")
    def test_page_error_aborts_without_sending(self, mock_api_cls):
        api = mock_api_cls.return_value
        api.get_product_list.side_effect = Exception("ozon down")

        result = self._run(mock_api_cls)

        self.assertEqual(result, [])
        api.update_remains.assert_not_called()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python manage.py test ozon.tests.CloseUnknownOzonStocksTest -v 2`
Expected: ERROR с `ImportError: cannot import name 'close_unknown_ozon_stocks'`

- [ ] **Step 3: Реализация**

В `ozon/tasks.py` после функции `update_remains_ozon` добавить (константу — рядом, на уровне модуля):

```python
OZON_WAREHOUSE_ID = 22865154657000


def _get_all_ozon_offer_ids(ozon_api):
    """Все неархивные offer_id с Ozon (пагинация /v3/product/list)."""
    offer_ids = set()
    last_id = ""
    while True:
        response = ozon_api.get_product_list(last_id=last_id)
        result = response.get('result', {})
        items = result.get('items', [])
        if not items:
            break
        for item in items:
            if not item.get('archived'):
                offer_ids.add(item['offer_id'])
        last_id = result.get('last_id') or ""
        if not last_id:
            break
    return offer_ids


def close_unknown_ozon_stocks(dry_run=False):
    """Обнуляет остаток на Ozon для карточек, которых нет в OzonData.

    dry_run=True — только лог списка, без отправки (для dev и первого прогона в проде).
    Возвращает список offer_id, которые были (были бы) обнулены.
    """
    ozon_api = OzonExchange()
    try:
        ozon_offer_ids = _get_all_ozon_offer_ids(ozon_api)
    except Exception as e:
        print(f"close_unknown_ozon_stocks: ошибка получения списка карточек: {e}")
        return []
    known = set(OzonData.objects.values_list('offer_id', flat=True))
    unknown = sorted(ozon_offer_ids - known)
    print(
        f"close_unknown_ozon_stocks: на Ozon {len(ozon_offer_ids)}, "
        f"в базе {len(known)}, к обнулению {len(unknown)}"
    )
    if dry_run:
        print(f"close_unknown_ozon_stocks (dry_run): {unknown}")
        return unknown
    for i in range(0, len(unknown), 100):
        chunk = unknown[i:i + 100]
        stocks = [
            {
                "offer_id": offer_id,
                "stock": 0,
                "warehouse_id": OZON_WAREHOUSE_ID,
                "quant_size": 1,
            }
            for offer_id in chunk
        ]
        response = ozon_api.update_remains(data=stocks)
        for res in (response or {}).get('result', []):
            if res.get('errors'):
                print(f"close_unknown_ozon_stocks: {res.get('offer_id')} ошибки {res['errors']}")
        time.sleep(1)  # страховка от лимита 80 req/min
    return unknown
```

Примечание: `import time` в `ozon/tasks.py` уже есть (строка 1).

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `python manage.py test ozon.tests.CloseUnknownOzonStocksTest -v 2`
Expected: PASS (5 тестов OK)

- [ ] **Step 5: Commit**

```bash
git add ozon/tasks.py ozon/tests.py
git commit -m "feat(ozon): обнуление остатков карточек, отсутствующих в OzonData"
```

---

### Task 3: интеграция в `update_remains_ozon`

**Files:**
- Modify: `ozon/tasks.py:244-268` (тело `update_remains_ozon`)
- Test: `ozon/tests.py`

**Interfaces:**
- Consumes: `close_unknown_ozon_stocks(dry_run=False) -> list[str]` (Task 2).
- Produces: `update_remains_ozon` (Celery `@shared_task`) в конце прогона вызывает `close_unknown_ozon_stocks()`; исключение из неё не роняет задачу.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `ozon/tests.py` (в конец файла):

```python
class UpdateRemainsOzonIntegrationTest(TestCase):
    @patch("ozon.tasks.close_unknown_ozon_stocks")
    @patch("ozon.tasks.OzonExchange")
    def test_calls_close_unknown_after_own_stocks(self, mock_api_cls, mock_close):
        from ozon.tasks import update_remains_ozon

        update_remains_ozon()

        mock_close.assert_called_once_with()

    @patch("ozon.tasks.close_unknown_ozon_stocks", side_effect=Exception("boom"))
    @patch("ozon.tasks.OzonExchange")
    def test_close_unknown_error_does_not_break_task(self, mock_api_cls, mock_close):
        from ozon.tasks import update_remains_ozon

        update_remains_ozon()  # не должно выбросить исключение

        mock_close.assert_called_once_with()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python manage.py test ozon.tests.UpdateRemainsOzonIntegrationTest -v 2`
Expected: FAIL с `AssertionError: Expected 'close_unknown_ozon_stocks' to be called once. Called 0 times.`

- [ ] **Step 3: Реализация**

В `ozon/tasks.py` в конце `update_remains_ozon` (после финальной отправки остатков, перед `print("end update remains OZON")`):

```python
    if len(stock) > 0:
        ozon_api.update_remains(data=stock)
    try:
        close_unknown_ozon_stocks()
    except Exception as e:
        print(f"update_remains_ozon: ошибка обнуления неизвестных карточек: {e}")
    print("end update remains OZON")
```

(Меняются только строки между `ozon_api.update_remains(data=stock)` и `print("end update remains OZON")` — добавляется блок try/except.)

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `python manage.py test ozon -v 2`
Expected: PASS — все тесты приложения ozon (8 шт.) OK

- [ ] **Step 5: Прогнать смежные тесты (регрессия)**

Run: `python manage.py test catalog order -v 1`
Expected: PASS без новых падений (эти приложения дёргают `update_remains_ozon` через мок)

- [ ] **Step 6: Commit**

```bash
git add ozon/tasks.py ozon/tests.py
git commit -m "feat(ozon): update_remains_ozon обнуляет остатки неизвестных карточек"
```

---

## Ввод в прод (вне кода, для оператора)

1. Деплой ветки на прод.
2. Первый прогон вручную из Django shell: `from ozon.tasks import close_unknown_ozon_stocks; close_unknown_ozon_stocks(dry_run=True)` — просмотреть список offer_id в логе.
3. Если список ожидаемый — ничего больше делать не нужно: боевой вызов уже встроен в `update_remains_ozon` и сработает при следующем обновлении каталога из 1С.
4. В dev реальные запросы не делать (база неактуальна — обнулит почти всё): только `dry_run=True` или тесты.
