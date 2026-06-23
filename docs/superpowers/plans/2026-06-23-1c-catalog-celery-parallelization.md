# Параллелизация обмена каталогом 1С через Celery — Implementation Plan

> **For agentic workers / Codex:** реализуй задачи по порядку, строго TDD
> (сначала падающий тест → запуск → минимальная реализация → запуск → коммит).
> Спека: `docs/superpowers/specs/2026-06-23-1c-catalog-celery-parallelization-design.md`.
> Шаги используют `- [ ]` для трекинга.

**Goal:** Превратить последовательный `get_data_1C()` в параллельный конвейер Celery
(реальные чанки + отдельная очередь картинок), не превышая ~4 одновременных запроса к 1С.

**Architecture:** `get_data_1C` — дирижёр: грузит справочники синхронно, затем рассылает
`process_catalog_chunk` через `chord(group(...))`; запись каталога ставит скачивание
картинок отдельной задачей `update_product_images` (очередь `images`); по завершении
всех чанков chord-callback `after_catalog_update` обновляет остатки на маркетплейсах.

**Tech Stack:** Django 5.2, Celery 5.5 (брокер/бэкенд Redis), requests + urllib3 Retry,
PostgreSQL. Тесты — `manage.py test` (`unittest.mock`).

## Global Constraints

- Прод-воркер: **4 ядра / 6 ГБ ОЗУ**. Команда: `celery -A lekala_ppf worker -Q catalog,images -c 4 --prefetch-multiplier=1 -O fair`.
- Потолок 1С: **≤4 параллельных запроса** (обеспечивается `-c 4`, доп. rate-limit не нужен).
- Ретраи только по **GET**: `429, 500, 502, 503, 504`, `total=2` (1 запрос + 2 повтора), `respect_retry_after_header=True`. `POST /order` НЕ ретраить.
- Интерпретатор/тесты: `.venv\Scripts\python.exe manage.py test catalog order --noinput`.
- Если тестовая БД не собирается (`django_content_type не существует`): сначала
  `.venv\Scripts\python.exe manage.py makemigrations catalog order ozon wildberries aliexpress avito yamarket`.
- Стиль ответа/комментариев — как в окружающем коде. Никаких новых зависимостей.

---

### Task 1: Ретраи 429/500 в `ExChange1C`

**Files:**
- Modify: `src/lekala_class/class_1C/ExChange1C.py` (Retry в `__init__`, ~стр. 21-26)
- Test: `catalog/tests.py` (новый класс в конце файла)

**Interfaces:**
- Produces: поведение сессии `ExChange1C().session` — adapter с `Retry(total=2, status_forcelist=[429,500,502,503,504], respect_retry_after_header=True, allowed_methods=["GET"])`.

- [ ] **Step 1: Написать падающий тест**

```python
# catalog/tests.py — добавить в конец
class ExChange1CRetryPolicyTest(TestCase):
    def test_retry_covers_429_and_500_with_two_retries(self):
        client = ExChange1C()
        retry = client.session.get_adapter("https://x/").max_retries
        self.assertIn(429, retry.status_forcelist)
        self.assertIn(500, retry.status_forcelist)
        self.assertEqual(retry.total, 2)
        self.assertTrue(retry.respect_retry_after_header)
```

- [ ] **Step 2: Запуск — убедиться, что падает**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.ExChange1CRetryPolicyTest --noinput`
Expected: FAIL (`429 not in status_forcelist` или `total != 2`).

- [ ] **Step 3: Минимальная реализация**

```python
# src/lekala_class/class_1C/ExChange1C.py — в __init__ заменить retry_strategy
        retry_strategy = Retry(
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        )
```

- [ ] **Step 4: Запуск — убедиться, что проходит**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.ExChange1CRetryPolicyTest --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lekala_class/class_1C/ExChange1C.py catalog/tests.py
git commit -m "feat(1c): ретраи 429/500 (total=2, Retry-After) на GET"
```

---

### Task 2: Настройки Celery — очереди, чанк, acks

**Files:**
- Modify: `lekala_ppf/settings.py` (после блока CELERY, ~стр. 162)
- Test: `catalog/tests.py`

**Interfaces:**
- Produces: `settings.CELERY_TASK_ROUTES`, `settings.CATALOG_CHUNK_SIZE` (int),
  `settings.CELERY_TASK_ACKS_LATE`, `settings.CELERY_WORKER_PREFETCH_MULTIPLIER`.

- [ ] **Step 1: Падающий тест**

```python
# catalog/tests.py
from django.conf import settings as dj_settings

class CeleryRoutingSettingsTest(TestCase):
    def test_queues_and_chunk_configured(self):
        routes = dj_settings.CELERY_TASK_ROUTES
        self.assertEqual(routes["catalog.tasks.update_product_images"]["queue"], "images")
        self.assertEqual(routes["catalog.tasks.process_catalog_chunk"]["queue"], "catalog")
        self.assertEqual(routes["catalog.tasks.after_catalog_update"]["queue"], "catalog")
        self.assertEqual(routes["catalog.tasks.get_data_1C"]["queue"], "catalog")
        self.assertIsInstance(dj_settings.CATALOG_CHUNK_SIZE, int)
        self.assertTrue(dj_settings.CELERY_TASK_ACKS_LATE)
        self.assertEqual(dj_settings.CELERY_WORKER_PREFETCH_MULTIPLIER, 1)
```

- [ ] **Step 2: Запуск — падает**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CeleryRoutingSettingsTest --noinput`
Expected: FAIL (`AttributeError: CELERY_TASK_ROUTES`).

- [ ] **Step 3: Реализация**

```python
# lekala_ppf/settings.py — после CELERY_TASK_SERIALIZER
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CATALOG_CHUNK_SIZE = 100
CELERY_TASK_ROUTES = {
    "catalog.tasks.get_data_1C": {"queue": "catalog"},
    "catalog.tasks.process_catalog_chunk": {"queue": "catalog"},
    "catalog.tasks.after_catalog_update": {"queue": "catalog"},
    "catalog.tasks.update_product_images": {"queue": "images"},
}
```

- [ ] **Step 4: Запуск — проходит**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CeleryRoutingSettingsTest --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lekala_ppf/settings.py catalog/tests.py
git commit -m "feat(celery): очереди catalog/images, CATALOG_CHUNK_SIZE, acks_late"
```

---

### Task 3: Флаг `async_images` в `set_catalog_data_stock`

**Files:**
- Modify: `src/lekala_class/class_1C/GetData1C.py` (`set_catalog_data_stock`, конец метода)
- Test: `catalog/tests.py`

**Interfaces:**
- Consumes: `catalog.tasks.update_product_images` (Task 5; импорт внутри метода).
- Produces: `GetData1C.set_catalog_data_stock(data_catalog, async_images=False)`.
  При `async_images=True` для каждого обновлённого товара вызывает
  `update_product_images.delay(str(product.uuid_1C))` вместо `self.get_img(...)`.

- [ ] **Step 1: Падающие тесты** (используют setUp из существующего `GetData1CCatalogStockTest`; добавить методы в этот класс)

```python
# catalog/tests.py — внутри класса GetData1CCatalogStockTest
    def test_async_images_enqueues_task_not_inline(self):
        with patch.object(GetData1C, "get_img") as get_img, \
             patch("catalog.tasks.update_product_images") as upi:
            self.data.set_catalog_data_stock([self._item()], async_images=True)
        get_img.assert_not_called()
        upi.delay.assert_called_once_with("7e019266-24a4-11ef-8009-00155d46f78d")

    def test_sync_images_calls_get_img_inline(self):
        with patch.object(GetData1C, "get_img") as get_img, \
             patch("catalog.tasks.update_product_images") as upi:
            self.data.set_catalog_data_stock([self._item()], async_images=False)
        get_img.assert_called_once()
        upi.delay.assert_not_called()
```

- [ ] **Step 2: Запуск — падает**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.GetData1CCatalogStockTest --noinput`
Expected: FAIL (`set_catalog_data_stock() got unexpected keyword 'async_images'`).

- [ ] **Step 3: Реализация** — заменить последнюю строку блока `if should_refresh_details:`

```python
# src/lekala_class/class_1C/GetData1C.py
    def set_catalog_data_stock(self, data_catalog, async_images=False):
        ...
                # (внутри if should_refresh_details, вместо self.get_img(product.uuid_1C))
                if async_images:
                    from catalog.tasks import update_product_images
                    update_product_images.delay(str(product.uuid_1C))
                else:
                    self.get_img(product.uuid_1C)
```

- [ ] **Step 4: Запуск — проходит** (и не сломан старый класс)

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.GetData1CCatalogStockTest --noinput`
Expected: PASS (включая прежние тесты маппинга).

- [ ] **Step 5: Commit**

```bash
git add src/lekala_class/class_1C/GetData1C.py catalog/tests.py
git commit -m "feat(1c): async_images — вынос картинок в celery-задачу"
```

---

### Task 4: Задача `update_product_images`

**Files:**
- Modify: `catalog/tasks.py`
- Test: `catalog/tests.py`

**Interfaces:**
- Produces: `catalog.tasks.update_product_images(uuid)` — `ExChange1C().get_img(uuid)`.

- [ ] **Step 1: Падающий тест**

```python
# catalog/tests.py
class CatalogImageTaskTest(TestCase):
    @patch("catalog.tasks.ExChange1C")
    def test_update_product_images_calls_get_img(self, exc):
        from catalog.tasks import update_product_images
        update_product_images("abc-uuid")
        exc.return_value.get_img.assert_called_once_with("abc-uuid")
```

- [ ] **Step 2: Запуск — падает**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CatalogImageTaskTest --noinput`
Expected: FAIL (`cannot import name 'update_product_images'`).

- [ ] **Step 3: Реализация** — добавить в `catalog/tasks.py`

```python
@shared_task
def update_product_images(uuid):
    ExChange1C().get_img(uuid)
```

- [ ] **Step 4: Запуск — проходит**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CatalogImageTaskTest --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catalog/tasks.py catalog/tests.py
git commit -m "feat(celery): задача update_product_images (очередь images)"
```

---

### Task 5: Задача `process_catalog_chunk`

**Files:**
- Modify: `catalog/tasks.py`
- Test: `catalog/tests.py`

**Interfaces:**
- Produces: `catalog.tasks.process_catalog_chunk(chunk)` →
  `GetData1C().set_catalog_data_stock(chunk, async_images=True)`.

- [ ] **Step 1: Падающий тест**

```python
# catalog/tests.py
class CatalogChunkTaskTest(TestCase):
    @patch("catalog.tasks.GetData1C")
    def test_process_catalog_chunk_uses_async_images(self, gd):
        from catalog.tasks import process_catalog_chunk
        chunk = [{"ref_key": "x"}]
        process_catalog_chunk(chunk)
        gd.return_value.set_catalog_data_stock.assert_called_once_with(
            chunk, async_images=True
        )
```

- [ ] **Step 2: Запуск — падает**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CatalogChunkTaskTest --noinput`
Expected: FAIL (`cannot import name 'process_catalog_chunk'`).

- [ ] **Step 3: Реализация** — заменить старую `get_data_chunck` в `catalog/tasks.py`

```python
@shared_task
def process_catalog_chunk(chunk):
    GetData1C().set_catalog_data_stock(chunk, async_images=True)
```
(старую функцию `get_data_chunck` удалить.)

- [ ] **Step 4: Запуск — проходит**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CatalogChunkTaskTest --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catalog/tasks.py catalog/tests.py
git commit -m "feat(celery): process_catalog_chunk вместо синхронного get_data_chunck"
```

---

### Task 6: Callback `after_catalog_update`

**Files:**
- Modify: `catalog/tasks.py`
- Test: `catalog/tests.py`

**Interfaces:**
- Produces: `catalog.tasks.after_catalog_update(results=None)` — дергает
  `update_remains_ozon.delay()`, `update_remains_wb.delay()`, `update_stock_ali.delay()`.

- [ ] **Step 1: Падающий тест**

```python
# catalog/tests.py
class CatalogAfterUpdateTest(TestCase):
    def test_after_catalog_update_triggers_marketplaces(self):
        import catalog.tasks as t
        with patch.object(t, "update_remains_ozon") as ozon, \
             patch.object(t, "update_remains_wb") as wb, \
             patch.object(t, "update_stock_ali") as ali:
            t.after_catalog_update()
        ozon.delay.assert_called_once_with()
        wb.delay.assert_called_once_with()
        ali.delay.assert_called_once_with()
```

- [ ] **Step 2: Запуск — падает**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CatalogAfterUpdateTest --noinput`
Expected: FAIL (`module 'catalog.tasks' has no attribute 'after_catalog_update'`).

- [ ] **Step 3: Реализация** — добавить в `catalog/tasks.py`

```python
@shared_task
def after_catalog_update(results=None):
    update_remains_ozon.delay()
    update_remains_wb.delay()
    # sent_stock_ya.delay()
    update_stock_ali.delay()
```

- [ ] **Step 4: Запуск — проходит**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CatalogAfterUpdateTest --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catalog/tasks.py catalog/tests.py
git commit -m "feat(celery): after_catalog_update — остатки в маркетплейсы после чанков"
```

---

### Task 7: Дирижёр `get_data_1C` (chord/group)

**Files:**
- Modify: `catalog/tasks.py` (`get_data_1C`, импорт celery)
- Test: `catalog/tests.py`

**Interfaces:**
- Consumes: `process_catalog_chunk` (T5), `after_catalog_update` (T6),
  `settings.CATALOG_CHUNK_SIZE` (T2).
- Produces: `get_data_1C()` — справочники синхронно → `get_all_products()` →
  `chord(group(process_catalog_chunk.s(c) for c in chunks))(after_catalog_update.s())`.

- [ ] **Step 1: Падающий тест**

```python
# catalog/tests.py
class GetData1COrchestratorTest(TestCase):
    @override_settings(CATALOG_CHUNK_SIZE=2)
    @patch("catalog.tasks.after_catalog_update")
    @patch("catalog.tasks.chord")
    @patch("catalog.tasks.group")
    @patch("catalog.tasks.process_catalog_chunk")
    @patch("catalog.tasks.GetData1C")
    def test_dispatches_chord_of_chunks(self, gd, pcc, group_mock, chord_mock, after):
        inst = gd.return_value
        inst.get_all_products.return_value = [
            {"ref_key": "1"}, {"ref_key": "2"}, {"ref_key": "3"}
        ]
        from catalog.tasks import get_data_1C
        get_data_1C()
        inst.set_name_attribute.assert_called_once()
        inst.set_type_price.assert_called_once()
        inst.set_category_catalog.assert_called_once()
        # 3 товара, размер 2 -> 2 чанка
        self.assertEqual(pcc.s.call_count, 2)
        chord_mock.assert_called_once_with(group_mock.return_value)
        chord_mock.return_value.assert_called_once_with(after.s.return_value)

    @override_settings(CATALOG_CHUNK_SIZE=2)
    @patch("catalog.tasks.chord")
    @patch("catalog.tasks.GetData1C")
    def test_empty_catalog_does_not_dispatch(self, gd, chord_mock):
        gd.return_value.get_all_products.return_value = []
        from catalog.tasks import get_data_1C
        get_data_1C()
        chord_mock.assert_not_called()
```

- [ ] **Step 2: Запуск — падает**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.GetData1COrchestratorTest --noinput`
Expected: FAIL (старый `get_data_1C` зовёт `get_data_chunck`/маркетплейсы напрямую).

- [ ] **Step 3: Реализация** — заменить `get_data_1C` и импорт в `catalog/tasks.py`

```python
# верх файла
from celery import chord, group, shared_task

@shared_task
def get_data_1C():
    print("START UPDATE ALL")
    data1C = GetData1C()
    data1C.set_name_attribute()
    data1C.set_type_price()
    data1C.set_category_catalog()
    items = data1C.get_all_products()
    if not items:
        return
    size = settings.CATALOG_CHUNK_SIZE
    chunks = [items[i:i + size] for i in range(0, len(items), size)]
    # Список (не генератор): сигнатуры строятся сразу, тестируемо при моке group.
    header = [process_catalog_chunk.s(chunk) for chunk in chunks]
    chord(group(header))(after_catalog_update.s())
```
(убрать прежние прямые `update_remains_*.delay()` из `get_data_1C` — они теперь в `after_catalog_update`.)

- [ ] **Step 4: Запуск — проходит**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.GetData1COrchestratorTest --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catalog/tasks.py catalog/tests.py
git commit -m "feat(celery): get_data_1C — chord(group(chunks)) + callback"
```

---

### Task 8: Полный прогон тестов + документация воркера

**Files:**
- Modify: `1c-dev-runbook.md` (примечание к шагу 4)
- (опц.) Create: короткая заметка по запуску воркера в README/runbook

- [ ] **Step 1: Полный прогон**

Run: `.venv\Scripts\python.exe manage.py test catalog order --noinput`
Expected: все тесты PASS (старые 25 + новые из задач 1–7), `System check ... no issues`.

- [ ] **Step 2: Обновить runbook** — шаг 4 теперь требует запущенного воркера

```markdown
# 1c-dev-runbook.md — в раздел «Шаг 4» добавить примечание:
> ⚠️ После параллелизации `get_data_1C` только СТАВИТ задачи в очереди и сразу
> возвращается. Чтобы они реально выполнились, нужен запущенный воркер:
> `celery -A lekala_ppf worker -Q catalog,images -c 4 --prefetch-multiplier=1 -O fair`
> (на Windows-dev — пул prefork; для боевого фона так же).
```

- [ ] **Step 3: Commit**

```bash
git add 1c-dev-runbook.md
git commit -m "docs: запуск воркера с очередями catalog/images, примечание к шагу 4"
```

---

## Self-Review (выполнено автором плана)

- **Покрытие спека:** Retry (T1) ↔ §4; routing/chunk (T2) ↔ §5.1; async_images (T3) ↔ §5.3;
  update_product_images (T4) ↔ §3.3/§5.4; process_catalog_chunk (T5) ↔ §5.4;
  after_catalog_update (T6) ↔ §3.3; get_data_1C chord (T7) ↔ §3.3/§5.4; воркер/runbook (T8) ↔ §3.2/§7. Пробелов нет.
- **Плейсхолдеров нет** — во всех code-шагах реальный код.
- **Согласованность имён:** `process_catalog_chunk`, `update_product_images`,
  `after_catalog_update`, `set_catalog_data_stock(..., async_images=)`,
  `CATALOG_CHUNK_SIZE` — едины во всех задачах.

## Последствия (важно для прод/dev)

- `get_data_1C` больше **не синхронный**: он ставит задачи и возвращается. Реальная
  обработка требует запущенного воркера на очередях `catalog,images`.
- Скрипт `c1_step4_full` теперь только enqueue’ит — наблюдать выполнение в воркере.
- Картинки докачиваются фоном независимо от обновления остатков маркетплейсов.

---

## Codex — промт запуска

```
Контекст: Django-проект D:\Work\Python\LekalaPPF, ветка
feature/1c-catalog-celery-parallelization. Делаем параллелизацию обмена каталогом 1С
через Celery.

ИСТОЧНИК ИСТИНЫ — два файла, прочитай первыми:
- docs/superpowers/plans/2026-06-23-1c-catalog-celery-parallelization.md (этот план)
- docs/superpowers/specs/2026-06-23-1c-catalog-celery-parallelization-design.md (спека)

Реализуй Задачи 1–8 строго по порядку и строго по TDD: для каждой задачи сначала
впиши падающий тест из шага 1, запусти и убедись что падает, затем минимальная
реализация, запусти и убедись что проходит, потом коммит с указанным сообщением.
Не отступай от имён: process_catalog_chunk, update_product_images,
after_catalog_update, set_catalog_data_stock(..., async_images=), CATALOG_CHUNK_SIZE.

Окружение:
- интерпретатор: .venv\Scripts\python.exe
- тесты: .venv\Scripts\python.exe manage.py test catalog order --noinput
- если тестовая БД не собирается (django_content_type не существует):
  .venv\Scripts\python.exe manage.py makemigrations catalog order ozon wildberries aliexpress avito yamarket
- НЕ добавляй новых зависимостей; не трогай POST /order (ретраи туда не нужны).

Готово, когда: все задачи закоммичены, полный прогон
`manage.py test catalog order --noinput` зелёный (старые 25 тестов + новые),
`manage.py check` без ошибок. Покажи финальный вывод тестов.
```
