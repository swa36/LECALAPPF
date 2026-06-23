# Правки по ревью параллелизации каталога 1С — Implementation Plan

> **For agentic workers / Codex:** реализуй задачи по порядку, строго TDD
> (падающий тест → запуск → реализация → запуск → коммит). Ветка
> `feature/1c-catalog-celery-parallelization`. Контекст: ревью выявило 2 important-проблемы.

**Goal:** Закрыть important-findings ревью: (1) downstream-задачи не теряются из-за
очередей; (2) один битый товар не отменяет весь chord и пуш остатков.

**Tech Stack:** Django 5.2, Celery 5.5 (Redis), PostgreSQL. Тесты — `manage.py test`.

## Global Constraints

- Интерпретатор/тесты: `.venv\Scripts\python.exe manage.py test catalog order --noinput`.
- Если тестовая БД не собирается: `.venv\Scripts\python.exe manage.py makemigrations catalog order ozon wildberries aliexpress avito yamarket`.
- Не добавлять зависимостей. Не трогать `POST /order`. Не ломать существующие 34 теста.
- Дефолтная celery-очередь — `celery` (не переопределена). Маршруты есть только у 4
  catalog-задач; всё остальное (ozon/wb/ali/order/yamarket + downstream `update_remains_*`,
  `update_stock_ali`, пуш картинок `update_img_ozon`/`sent_img_video`) идёт в `celery`.

---

### Task 1: Устойчивость чанка — битый товар не роняет `process_catalog_chunk`

**Проблема (ревью #2):** `set_catalog_data_stock` падает на `Category.objects.get(...)`
для товара с категорией вне дерева → весь `process_catalog_chunk` падает → chord не
вызывает `after_catalog_update` → остатки не уходят на маркетплейсы за весь прогон.

**Files:**
- Modify: `src/lekala_class/class_1C/GetData1C.py` (`set_catalog_data_stock`, тело цикла)
- Test: `catalog/tests.py` (в класс `GetData1CCatalogStockTest`)

**Interfaces:**
- Produces: `set_catalog_data_stock` пропускает товар, на котором возникло исключение
  (лог + `continue`), и продолжает обработку остальных. Сигнатура без изменений.

- [ ] **Step 1: Падающий тест** — добавить метод в `GetData1CCatalogStockTest`

```python
    def test_bad_item_is_skipped_and_chunk_continues(self):
        bad = self._item()
        bad["ref_key"] = "abcdefab-1234-1234-1234-abcdefabcdef"
        bad["parent_key"] = "fefefefe-fefe-fefe-fefe-fefefefefefe"  # нет такой категории
        good = self._item()  # parent_key = существующая категория из setUp
        with patch.object(self.data, "get_img"):
            self.data.set_catalog_data_stock([bad, good])  # не должно бросать
        self.assertTrue(
            Product.objects.filter(uuid_1C=good["ref_key"]).exists()
        )
        self.assertFalse(
            Product.objects.filter(uuid_1C=bad["ref_key"]).exists()
        )
```

- [ ] **Step 2: Запуск — падает**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.GetData1CCatalogStockTest.test_bad_item_is_skipped_and_chunk_continues --noinput`
Expected: FAIL — `Category.DoesNotExist` пробрасывается из метода.

- [ ] **Step 3: Реализация** — обернуть тело цикла в try/except

```python
# src/lekala_class/class_1C/GetData1C.py — внутри set_catalog_data_stock
        for item in data_catalog:
            try:
                stock = max(int(item.get("in_stock") or 0), 0)
                product_before = Product.objects.filter(uuid_1C=item["ref_key"]).first()
                should_refresh_details = (
                    product_before is None
                    or product_before.data_version != item.get("data_version")
                )

                product, created = Product.objects.update_or_create(
                    uuid_1C=item["ref_key"],
                    defaults={
                        "article_1C": item["article"].strip(),
                        "code_1C": item["code"],
                        "data_version": item.get("data_version") or "",
                        "name": item["description"].strip(),
                        "description": item["description_text"],
                        "stock": stock,
                        "main_img_uuid": item.get("picture_file_key") or None,
                        "category": Category.objects.get(uuid_1C=item["parent_key"]),
                    },
                )

                price_by_type = {
                    str(price["price_type_key"]): price.get("price", 0)
                    for price in item.get("prices", [])
                }
                price_dict = {
                    type_price.suffix: price_by_type.get(str(type_price.uuid_1C), 0)
                    for type_price in type_prices
                }
                Prices.objects.update_or_create(product=product, defaults=price_dict)

                if should_refresh_details:
                    print(
                        f"Создана/обновлена номенклатура "
                        f"{product.name} {product.article_1C}"
                    )
                    if created:
                        os.makedirs("logs", exist_ok=True)
                        with open("logs/new_item.log", "a", encoding="utf-8") as log_file:
                            log_file.write(
                                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\t"
                                f"{product.name}\t{product.article_1C}\t{product.code_1C}\n"
                            )

                    for attribute in item.get("additional_attributes", []):
                        ValueAdditionalAttributes.objects.update_or_create(
                            product=product,
                            attribute_name=NameAdditionalAttributes.objects.get(
                                uuid_1C=attribute["property_key"]
                            ),
                            defaults={"value_attribute": attribute["value"]},
                        )

                    if async_images:
                        from catalog.tasks import update_product_images

                        update_product_images.delay(str(product.uuid_1C))
                    else:
                        self.get_img(product.uuid_1C)
            except Exception as exc:
                print(f"Пропущен товар {item.get('ref_key')}: {exc}")
                continue
```

- [ ] **Step 4: Запуск — проходит** (и старые тесты класса целы)

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.GetData1CCatalogStockTest --noinput`
Expected: PASS (все методы класса).

- [ ] **Step 5: Commit**

```bash
git add src/lekala_class/class_1C/GetData1C.py catalog/tests.py
git commit -m "fix(1c): битый товар пропускается, не роняя чанк/chord"
```

---

### Task 2: Контракт chord-callback — `after_catalog_update` принимает позиционный results

**Проблема (ревью, тест #3):** chord передаёт callback список результатов хедера
первым позиционным аргументом. Сейчас это работает (`results=None`), но не зафиксировано
тестом — легко сломать.

**Files:**
- Test: `catalog/tests.py` (в класс `CatalogAfterUpdateTest`)

- [ ] **Step 1: Падающий/новый тест**

```python
    def test_after_catalog_update_accepts_positional_results(self):
        import catalog.tasks as t
        with patch.object(t, "update_remains_ozon") as ozon, \
             patch.object(t, "update_remains_wb") as wb, \
             patch.object(t, "update_stock_ali") as ali:
            t.after_catalog_update([1, 2, 3])  # как вызовет chord
        ozon.delay.assert_called_once_with()
        wb.delay.assert_called_once_with()
        ali.delay.assert_called_once_with()
```

- [ ] **Step 2: Запуск**

Run: `.venv\Scripts\python.exe manage.py test catalog.tests.CatalogAfterUpdateTest --noinput`
Expected: PASS сразу (контракт уже соблюдён сигнатурой `results=None`). Это
регрессионный тест-замок; если он падает — значит сигнатуру кто-то сломал.

- [ ] **Step 3: Commit**

```bash
git add catalog/tests.py
git commit -m "test(celery): зафиксировать контракт after_catalog_update(results)"
```

---

### Task 3: Документация воркера — слушать дефолтную очередь

**Проблема (ревью #1):** команда только со специализированными очередями НЕ потребляет дефолтную очередь
`celery`, куда уходят все downstream-задачи (`update_remains_*`, `update_stock_ali`,
пуш картинок) и все прочие 19 задач проекта → они зависнут.

**Files:**
- Modify: `1c-dev-runbook.md` (примечание к шагу 4)
- Modify: `docs/superpowers/specs/2026-06-23-1c-catalog-celery-parallelization-design.md` (§3.2)
- Modify: `docs/superpowers/plans/2026-06-23-1c-catalog-celery-parallelization.md` (Global Constraints)

- [ ] **Step 1: Правка команды воркера во всех трёх файлах**

Везде заменить старую команду воркера без дефолтной очереди
```
celery -A lekala_ppf worker -Q celery,catalog,images -c 4 --prefetch-multiplier=1 -O fair
```
на
```
celery -A lekala_ppf worker -Q celery,catalog,images -c 4 --prefetch-multiplier=1 -O fair
```
и добавить рядом строку-предупреждение:
> ⚠️ Дефолтную очередь `celery` обязательно включать: туда идут `update_remains_*`,
> `update_stock_ali`, пуш картинок и все прочие задачи проекта. Без неё каталог
> обновится, но остатки/картинки на маркетплейсы не уедут.

- [ ] **Step 2: Проверка** — старой команды без дефолтной очереди не осталось

Run: проверить grep по старому фрагменту очередей без `celery`
Expected: пусто (все вхождения теперь `-Q celery,catalog,images`).

- [ ] **Step 3: Commit**

```bash
git add 1c-dev-runbook.md docs/superpowers/specs/2026-06-23-1c-catalog-celery-parallelization-design.md docs/superpowers/plans/2026-06-23-1c-catalog-celery-parallelization.md
git commit -m "docs: воркер слушает дефолтную очередь celery (иначе downstream висит)"
```

---

### Task 4: Финальный прогон

- [ ] **Step 1:** `.venv\Scripts\python.exe manage.py test catalog order --noinput` → все PASS (было 34 + новые из Task 1/2).
- [ ] **Step 2:** `.venv\Scripts\python.exe manage.py check` → без ошибок.

---

## Self-Review (автор плана)

- Покрытие findings: #2 → Task 1 (код+тест); контракт callback → Task 2 (тест-замок);
  #1 → Task 3 (доки во всех трёх местах + grep-проверка). Minor-замечания (идемпотентность
  redelivery, слот на пагинацию, неиспользуемый `sent_stock_ya`) — осознанно НЕ трогаем
  (benign/преэкзистинг), чтобы не раздувать диф.
- Плейсхолдеров нет, код в шагах полный.
- Имена согласованы: `set_catalog_data_stock(..., async_images=)`, `after_catalog_update(results=None)`, очереди `celery,catalog,images`.

---

## Codex — промт запуска

```
Контекст: Django-проект D:\Work\Python\LekalaPPF, ветка
feature/1c-catalog-celery-parallelization. Закрываем findings ревью параллелизации.

ИСТОЧНИК ИСТИНЫ — прочитай первым:
docs/superpowers/plans/2026-06-23-1c-catalog-celery-fixes.md

Реализуй Задачи 1–4 строго по порядку и строго по TDD: для каждой сначала впиши
тест из шага 1, запусти и убедись в результате (Task 1 — должен упасть; Task 2 —
должен пройти сразу как регрессионный замок), затем правка, запусти, коммит с
указанным сообщением.

Суть:
- Task 1: обернуть тело цикла в set_catalog_data_stock в try/except (лог + continue),
  чтобы битый товар (например, Category.DoesNotExist) не ронял весь чанк и chord.
- Task 2: регрессионный тест, что after_catalog_update принимает позиционный results.
- Task 3: во ВСЕХ трёх доках (runbook, spec §3.2, plan Global Constraints) заменить
  команду воркера на `-Q celery,catalog,images` и добавить предупреждение; проверить
  grep по старому фрагменту очередей без `celery` → пусто.
- Task 4: финальный прогон тестов и check.

Окружение:
- интерпретатор: .venv\Scripts\python.exe
- тесты: .venv\Scripts\python.exe manage.py test catalog order --noinput
- если БД не собирается: .venv\Scripts\python.exe manage.py makemigrations catalog order ozon wildberries aliexpress avito yamarket
- НЕ добавляй зависимостей; НЕ трогай POST /order; не меняй прочую логику.

Готово, когда: все задачи закоммичены, `manage.py test catalog order --noinput`
зелёный, `manage.py check` без ошибок, grep по старому фрагменту очередей без `celery` пусто.
Покажи финальный вывод тестов.
```
