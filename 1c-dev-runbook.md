# Раннбук: обкатка нового обмена с 1С на dev (по шагам)

4 скрипта в папке `scripts/`, запускаются через `manage.py runscript`.
Идём строго по порядку, после каждого шага смотрим вывод и решаем, идти ли дальше.

> **Перед стартом:** dev-машина должна видеть `terminal.scloud.ru`, в `lekala_ppf/.env`
> должны быть валидные `LOGIN_1C` / `PASSWORD_1C` (и при необходимости `BASE_URL_1C_HS`,
> иначе он выведется из `BASE_URL_1C` заменой `/odata/standard.odata/` → `/hs/prokopov/`).
> Команды — для Windows PowerShell. Если запускаешь из bash — замени `\` на `/`.

---

## Шаг 1 — Чистое чтение (smoke-тест). Ничего не пишет.

Проверяет, что живой сервис отвечает и поля совпадают с контрактом.

```powershell
.venv\Scripts\python.exe manage.py runscript c1_step1_read
```

✅ **Идти дальше, если** в конце «контракт ПОДТВЕРЖДЁН» и по эндпоинтам `[OK]`.
🛑 **Стоп, если** есть `[FAIL]` или «нет оболочки пагинации» — сперва разобраться
(не тот URL / сервис не опубликован / поля называются иначе).

---

## Шаг 2 — Справочники в БД (безопасно, идемпотентно).

Грузит характеристики, виды цен, дерево категорий. Нужно до товаров.

```powershell
.venv\Scripts\python.exe manage.py runscript c1_step2_refs
```

✅ Должны напечататься ненулевые счётчики и маппинг видов цен (`Розничная -> retail_price` …).
🛑 Если падает `KeyError` на виде цены — в 1С появился вид цены, которого нет в маппинге
`set_type_price` (добавить его в словарь).

---

## Шаг 3 — Один товар end-to-end (проверка маппинга).

Берёт первый товар и кладёт его в БД. **Картинки по умолчанию НЕ трогает.**

```powershell
.venv\Scripts\python.exe manage.py runscript c1_step3_one_product
```

С реальной загрузкой картинок одного товара (тронет `media/`):

```powershell
.venv\Scripts\python.exe manage.py runscript c1_step3_one_product --script-args withimg
```

✅ Глазами проверь: `name`, `article_1C`, `stock`, `prices` адекватные.
🛑 Если `Category matching query does not exist` — не выполнен шаг 2 или у товара
категория вне дерева.

---

## Шаг 4 — Полный прогон каталога.

Перезаписывает **весь** каталог в dev-БД, обновляет изображения. Запускается только
с `CONFIRM`. Отправка остатков на маркетплейсы по умолчанию **заглушена**.

Каталог в БД, **без** отправки на маркетплейсы (рекомендуется первым):

```powershell
.venv\Scripts\python.exe manage.py runscript c1_step4_full --script-args CONFIRM
```

Полностью, **с** отправкой остатков на OZON/WB/Ali (только когда уверен):

```powershell
.venv\Scripts\python.exe manage.py runscript c1_step4_full --script-args CONFIRM push
```

> ⚠️ Вариант с `push` реально шлёт данные на боевые маркетплейсы. Перед ним убедись,
> что каталог/остатки после шагов 1–3 выглядят корректно.

> ⚠️ После параллелизации `get_data_1C` только СТАВИТ задачи в очереди и сразу
> возвращается. Чтобы они реально выполнились, нужен запущенный воркер:
> `celery -A lekala_ppf worker -Q catalog,images -c 4 --prefetch-multiplier=1 -O fair`
> (на Windows-dev — пул prefork; для боевого фона так же).

---

## Памятка

| Что | Команда |
|---|---|
| 1. Чтение (smoke) | `runscript c1_step1_read` |
| 2. Справочники | `runscript c1_step2_refs` |
| 3. Один товар | `runscript c1_step3_one_product` |
| 3b. Один товар + картинки | `runscript c1_step3_one_product --script-args withimg` |
| 4. Полный, без маркетплейсов | `runscript c1_step4_full --script-args CONFIRM` |
| 4b. Полный, с маркетплейсами | `runscript c1_step4_full --script-args CONFIRM push` |

Полный префикс команды: `.venv\Scripts\python.exe manage.py <команда>`.

Заказы (`POST /order`) сюда не входят — это отдельная ветка, и там до боевого
запуска нужно подтвердить значение `Покупатель` (см. finding #1 в ревью / handoff).
