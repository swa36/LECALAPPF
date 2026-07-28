# Команды обслуживания

Справочник по синхронизации с 1С и обслуживанию маркетплейсов.

Общий принцип команд чистки: **без флага — только отчёт, с `--apply` — изменения**.
Всегда сначала отчёт.

---

## Запуск celery

Воркер обслуживает очереди `celery`, `catalog`, `images`.

**Прод (Linux):**

```bash
sudo systemctl restart celery
journalctl -u celery -f          # смотреть лог
```

```bash
celery -A lekala_ppf worker -l info -Q celery,catalog,images -c 4 -O fair
celery -A lekala_ppf beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

**Локально (Windows)** — обязателен пул `solo` или `threads`, prefork не работает:

```powershell
uv run celery -A lekala_ppf worker -l info -P solo -Q celery,catalog,images
uv run celery -A lekala_ppf beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

После `git pull` воркер **обязательно** перезапустить — иначе он держит в памяти
старый код.

---

## Синхронизация с 1С

### Полная синхронизация каталога

```bash
python manage.py shell -c "from catalog.tasks import get_data_1C; print(get_data_1C.delay().id)"
```

Асинхронно, нужен живой воркер. Порядок внутри: атрибуты → виды цен →
категории → товары чанками по 100 → метка «архив» → остатки на WB и Ali.

### Только категории

```bash
python manage.py shell -c "from src.lekala_class.class_1C.GetData1C import GetData1C; GetData1C().set_category_catalog()"
```

Синхронно, воркер не нужен. Печатает `Категории обновлены: N`. Если видишь
`1С не вернула ни одной категории` — дальше не иди, проблема в доступе к 1С.

---

## Чистка каталога

### `prune_categories` — категории, удалённые в 1С

Категория, перенесённая в 1С в «Удалено(архив)», пропадает из `/categories`,
но на сайте остаётся. Если её завели заново с новым `ref_key` — появляется дубль
по названию.

```bash
python manage.py prune_categories            # отчёт
python manage.py prune_categories --apply    # выполнить
python manage.py prune_categories --apply --force
```

Строки отчёта:

| Строка | Что произойдёт |
|---|---|
| `удаление` | пустая категория, просто исчезнет |
| `товары (N) → «имя» [uuid], затем удаление` | товары переедут на актуального двойника |
| `ПРОПУСК: есть товары, актуальный двойник не найден` | не тронет |
| `ПРОПУСК: есть живые подкатегории` | не тронет |

Защиты: пустая выгрузка — прерывается; больше 20% категорий под удаление —
требует `--force`. Всё в транзакции, в конце `rebuild()` дерева MPTT.

### `prune_products` — товары, которых нет в выгрузке 1С

```bash
python manage.py prune_products                       # отчёт
python manage.py prune_products --show 0              # весь список
python manage.py prune_products --zero-stock --apply  # снять с продажи (обратимо)
python manage.py prune_products --apply               # удалить безвозвратно
```

После внедрения метки «архив» удаление не нужно — синхронизация сама снимает
такие товары с продажи. Команда остаётся диагностикой: строка
**«с остатком > 0» должна быть 0**.

Не трогает товары, встречающиеся в заказах: у `OrderAvito.product` каскад снёс бы
сам заказ, а позиции заказов ссылаются через `GenericForeignKey`, который Django
не защищает.

### `check_duplicates` — товары-дубли

```bash
python manage.py check_duplicates              # по article_1C
python manage.py check_duplicates --by code    # по code_1C
python manage.py check_duplicates --by name    # по названию
python manage.py check_duplicates --check-1c   # + сверка с выгрузкой 1С
python manage.py check_duplicates --limit 20
```

Только читает. Дубль артикула ломает интеграции: товар ищется через
`Product.objects.get(article_1C=...)`, что на дублях падает с
`MultipleObjectsReturned`, и карточка молча пропускается.

**Правится только в 1С** — на стороне сайта чинить нечем.

---

## Wildberries

### `trash_archived_wb` — карточки архивных товаров в корзину

```bash
python manage.py trash_archived_wb            # отчёт
python manage.py trash_archived_wb --show 0   # весь список
python manage.py trash_archived_wb --apply    # перенести
```

Берёт товары с меткой `is_archive`, пропускает те, что уже в корзине.
Пачками по 500 с паузой 20 секунд под лимит WB (3 запроса в минуту).

Запускать **после** того, как синхронизация разнесла нулевые остатки: карточка
продаётся, пока по ней есть остатки.

Восстановление — вручную через `v2/cards/recover`. WB чистит корзину через
30 дней.

### `add_new_wb` — завести новые карточки на WB

```bash
python manage.py add_new_wb                    # отчёт
python manage.py add_new_wb --limit 5 --apply  # пробный запуск на 5 товарах
python manage.py add_new_wb --apply            # завести все
python manage.py add_new_wb --show 0           # весь список пропущенных
```

Берёт товары без карточки WB, кроме архивных и категории «Инструмент и
оборудование для нанесения плёнок».

Пропускает и показывает отдельно две группы:

- **не хватает атрибутов** — не заполнены `material`, `width`, `length`,
  `equipment`, `color` или нет розничной цены. Такие карточка WB не примет;
- **артикул уже занят карточкой на WB** — карточка там есть, а связки `WBData`
  в базе нет, поэтому товар выглядит как «без карточки». Отправка вернула бы
  `bad request; the specified card's vendor code is used in other cards`.

Перед заведением команда выкачивает `vendorCode` всех карточек WB, включая
корзину. Если WB список не отдал (401, сеть) — заведение отменяется целиком,
чтобы не наплодить дублей.

**Сначала подтяни потерянные связки**, иначе половина товаров окажется во второй
группе:

```bash
python manage.py set_id_wb
```

⚠️ **Отправка идёт по одной карточке с паузой 5 секунд.** На тысяче товаров это
несколько часов, процесс нельзя прерывать на середине вслепую — часть карточек
уже создастся. Начинай с `--limit 5 --apply`, проверь результат в личном
кабинете, только потом запускай всё.

После создания карточек подтяни их идентификаторы в базу командой `set_id_wb`,
иначе связки `WBData` не появится.

Непрошедшие карточки — в `v2/cards/error/list`.

### `set_id_wb` — привязать карточки WB к товарам

```bash
python manage.py set_id_wb                     # все карточки
python manage.py set_id_wb --param withoutImg  # только без фото
python manage.py set_id_wb --param withImg     # только с фото
```

Заполняет `WBData` по совпадению `article_1C` и `vendorCode`. Печатает, на
сколько прибавилось связок.

Карточки, которые привязать не вышло, выводятся с причиной:

| Причина | Что делать |
|---|---|
| `товара с таким артикулом нет в базе` | товар удалён из 1С либо артикул разошёлся — смотри `update_vendor_code_wb` |
| `артикул задублирован в 1С` | развести артикулы в 1С, на сайте не лечится |
| `у карточки нет баркода` | завести баркод в личном кабинете WB |

### `sent_img_wb` — залить изображения на карточки

```bash
python manage.py sent_img_wb                   # отчёт по карточкам без фото
python manage.py sent_img_wb --apply           # отправить
python manage.py sent_img_wb --param all --apply
```

По умолчанию берёт карточки без фото — им изображения и нужны. Товары без
картинок на сайте пропускает и показывает отдельно.

### `prune_wbdata` — связки с несуществующими карточками

```bash
python manage.py prune_wbdata                        # отчёт
python manage.py prune_wbdata --apply                # удалить связки
python manage.py prune_wbdata --include-trash --apply
```

Сверяется с актуальными карточками и корзиной, делит записи на две группы:

- **в корзине WB** — по умолчанию не удаляет, их ещё можно вернуть;
- **нет на WB вообще** — удаляются по `--apply`.

Удаляется только запись `WBData` — товар, цены и категория остаются.

⚠️ Восстановить связку тяжело: `set_id_wb` ищет товар по
`article_1C == vendorCode`, а у части карточек артикулы разошлись.

### `update_vendor_code_wb` — синхронизация артикулов

```bash
# отчёт, на WB ничего не уходит
python manage.py shell -c "from wildberries.tasks import update_vendor_code_wb; update_vendor_code_wb(dry_run=True)"

# отправка
python manage.py shell -c "from wildberries.tasks import update_vendor_code_wb; update_vendor_code_wb()"
```

Приводит `vendorCode` на WB к `article_1C`. Карточка ищется по `nmID`, а не по
артикулу, поэтому связка не рвётся, когда артикул уже разъехался.

**Сверяй список глазами перед отправкой.** По каждой карточке выводится три
строки — старый и новый артикул, `title` с WB и название товара в базе. Если
названия про разные машины, это битая привязка: чинить надо `WBData`, а не
артикул на маркетплейсе.

Пачками по 100 с паузой 7 секунд (лимит 10 запросов в минуту). Применяется до
30 минут, непрошедшие карточки — в `v2/cards/error/list`.

---

## AliExpress

### `reconcile_ali` — сверка карточек с каталогом

```bash
python manage.py reconcile_ali              # dry-run, ничего не меняет
python manage.py reconcile_ali --execute    # выполнить
```

Тянет все карточки с Ali и строит план. Под удаление попадают:

- карточки без SKU (`missing SKU`);
- карточки, чьего `code_1C` нет в каталоге (`missing local products`);
- дубли по одному `code_1C` (`duplicates`) — остаётся самая старая из уже
  связанных, остальные удаляются.

Дополнительно обновляет остатки по товарам с `stock > 0` и возвращает в онлайн
карточки со статусом `offline`.

Удаление идёт пачками по 20, обновление остатков — по 400, связки — по 1000.
Между запросами можно прервать по Ctrl+C — команда останавливается безопасно.

Удалённые карточки чистятся и локально: соответствующие `AliData` удаляются.

### Задачи Ali

```bash
# сопоставить карточки Ali с товарами и удалить лишние
python manage.py shell -c "from aliexpress.tasks import set_id_ali; set_id_ali.delay()"

# остатки
python manage.py shell -c "from aliexpress.tasks import update_stock_ali; update_stock_ali.delay()"

# заказы
python manage.py shell -c "from aliexpress.tasks import get_order_ali; get_order_ali.delay()"
```

`update_stock_ali` вызывается автоматически в конце полной синхронизации
(`after_catalog_update`).

## Фиды

```bash
python manage.py shell -c "from avito.tasks import create_feed; create_feed.delay()"
python manage.py shell -c "from aliexpress.tasks import create_feed_ALI; create_feed_ALI.delay()"
```

Фиды фильтруют `stock > 0` и `is_archive = False`, поэтому архивные товары
выпадают автоматически.

## Ozon

```bash
# остатки
python manage.py shell -c "from ozon.tasks import update_remains_ozon; update_remains_ozon.delay()"

# цены
python manage.py shell -c "from ozon.tasks import update_price_ozon; update_price_ozon.delay()"

# завести новые карточки
python manage.py shell -c "from ozon.tasks import add_new_item_ozon; add_new_item_ozon()"

# обнулить остатки карточек, которых нет в OzonData
python manage.py shell -c "from ozon.tasks import close_unknown_ozon_stocks; close_unknown_ozon_stocks(dry_run=True)"
```

⚠️ В `ozon/tasks.py` есть `close_all_ozon_sales` — **аварийная остановка продаж**,
обнуляет остаток по всем карточкам. По умолчанию `dry_run=True`; запускать
только осознанно.

---

## Проверка состояния

```bash
python manage.py shell -c "
from catalog.models import Product
print('Всего товаров:      ', Product.objects.count())
print('Архивных:           ', Product.objects.filter(is_archive=True).count())
print('Архивных с остатком:', Product.objects.filter(is_archive=True, stock__gt=0).count(), '<- должно быть 0')
print('Архивных с WB:      ', Product.objects.filter(is_archive=True, wb__isnull=False).count())
print('Живых в продаже:    ', Product.objects.filter(is_archive=False, stock__gt=0).count())
"
```

```bash
tail -30 logs/archived_1c.log     # что снято с продажи и что вернулось
tail -30 logs/new_item.log        # новая номенклатура
```

**Красные флаги:**

- архивных вышло на порядок больше обычного — выгрузка пришла неполной;
- архивных 0 — метка не проставилась, ищи в логе celery строку
  `Выгрузка 1С подозрительно мала`;
- «живых в продаже» заметно меньше размера выгрузки 1С — сняли лишнее.

---

## Полный прогон на проде

```bash
cd /var/www/LECALAPPF
source .venv/bin/activate

git fetch origin && git reset --hard origin/master

python manage.py showmigrations catalog
python manage.py migrate

sudo systemctl restart celery

python manage.py shell -c "from catalog.tasks import get_data_1C; print(get_data_1C.delay().id)"
```

Дождись в логе celery `START UPDATE ALL`, затем строки о метке «архив» и
обновлении остатков. После этого:

```bash
python manage.py prune_products | head -12    # "с остатком > 0" должно быть 0
python manage.py trash_archived_wb            # отчёт
python manage.py trash_archived_wb --apply
```

---

## Как это работает вместе

Метка `Product.is_archive` — единая точка. Товар, пропавший из выгрузки 1С,
получает метку и нулевой остаток, дальше всё расходится само:

| Куда             | Что происходит  | Механизм                                  |
| ---------------- | --------------- | ----------------------------------------- |
| WB               | остаток 0       | `update_remains_wb` берёт `stock` из базы |
| Ozon             | остаток 0       | `update_remains_ozon`                     |
| Ali              | остаток 0       | `update_stock_ali`                        |
| Фиды Ali, Avito  | товар исчезает  | фильтр `is_archive=False`                 |
| Новые карточки   | не заводятся    | `add_new_item_wb`, `add_new_item_ozon`    |
| Карточки WB      | в корзину       | `trash_archived_wb`, вручную              |

Вернут товар из архива в 1С — метка снимется, остаток приедет из выгрузки,
товар вернётся в продажу сам.

Когда 1С начнёт отдавать `deletion_mark`, метку начнёт ставить
`set_catalog_data_stock` — код уже готов, правок не потребуется. Подробности и
требования к 1С-специалисту:
`docs/superpowers/specs/2026-07-28-product-archive-flag-design.md`.
