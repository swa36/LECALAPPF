# Деплой на прод: миграция 1С (/hs/prokopov) + параллелизация Celery

Ветка `feature/1c-catalog-celery-parallelization` несёт **обе** части:
полную миграцию обмена 1С (OData → `/hs/prokopov/`, новый `POST /order`) и
распараллеливание каталога через Celery. **Изменений моделей нет → миграции БД не нужны.**

Прод: `/var/www/LECALAPPF/`, venv `/var/www/LECALAPPF/.venv/bin/`,
конфиг celery `/etc/systemd/celery.conf`, юнит `/etc/systemd/system/celery.service`.
Команды — для прод-Linux (prefork-пул, виндовых проблем нет).

---

## 0. Pre-flight (до выкатки, ничего не ломает)

- [ ] **Сервис `prokopov` опубликован** в 1С и доступен с прод-сервера под прод-кредами.
- [ ] **`BASE_URL_1C_HS`** на проде корректен. По умолчанию выводится из `BASE_URL_1C`
      заменой `/odata/standard.odata/` → `/hs/prokopov/`. Проверить:
      ```bash
      cd /var/www/LECALAPPF
      .venv/bin/python -c "from django.conf import settings; import django; django.setup()" 2>/dev/null; \
      .venv/bin/python manage.py shell -c "from django.conf import settings; print(settings.BASE_URL_1C_HS)"
      ```
      Должно оканчиваться на `/hs/prokopov/`. Если нет — прописать `BASE_URL_1C_HS` явно в `.env`.
- [ ] **Бэкап БД** (на всякий, хоть миграций и нет):
      ```bash
      .venv/bin/python manage.py dbbackup
      ```
- [ ] Зафиксировать текущую ветку прода для отката: `git -C /var/www/LECALAPPF rev-parse --abbrev-ref HEAD`.

---

## 1. Выкатка кода

```bash
cd /var/www/LECALAPPF
git fetch origin
git checkout feature/1c-catalog-celery-parallelization
git pull
.venv/bin/pip install -r req.txt            # зависимостей не добавляли, но на всякий
.venv/bin/python manage.py migrate          # no-op: новых миграций нет
.venv/bin/python manage.py collectstatic --noinput   # если статика обслуживается Django
```

- [ ] `manage.py check` без ошибок:
      ```bash
      .venv/bin/python manage.py check
      ```

---

## 2. Smoke-тест живого 1С (read-only, безопасно)

```bash
.venv/bin/python manage.py runscript c1_step1_read
```

- [ ] Вывод заканчивается «контракт ПОДТВЕРЖДЁН», по эндпоинтам `[OK]`.
🛑 Если `[FAIL]`/«нет оболочки пагинации» — **СТОП**, откат (раздел 6). Не публиковать дальше.

---

## 3. Обновить конфиг Celery

- [ ] `/etc/systemd/celery.conf` → `CELERYD_OPTS` (см. отдельные файлы, что я давал):
      на этапе пробы **временно без `celery`**, чтобы изолировать от пуша на маркетплейсы и отправки заказов:
      ```ini
      CELERYD_OPTS="-Q catalog,images -c 4 -O fair"
      ```
- [ ] `/etc/systemd/system/celery.service` — без `ExecStartPre ... purge` (новая версия).
- [ ] Применить:
      ```bash
      sudo systemctl daemon-reload
      sudo systemctl restart celery
      sudo systemctl restart gunicorn   # веб-приложение тоже использует новый код 1С
      sudo journalctl -u celery -n 60 --no-pager | grep -A4 queues
      ```
      В очередях старта должны быть `catalog` и `images`.

> На время пробы можно **остановить beat**, чтобы плановые задачи не стартовали сами:
> `sudo systemctl stop celerybeat` (или как назван beat-юнит).

---

## 4. Проба каталога (без маркетплейсов и без заказов)

```bash
cd /var/www/LECALAPPF
.venv/bin/python manage.py shell -c "from catalog.tasks import get_data_1C; print(get_data_1C.delay())"
```

- [ ] В логе воркера видно `get_data_1C` → `process_catalog_chunk` → `update_product_images`.
- [ ] Каталог в БД обновился (товары/цены/остатки), картинки появились в `media/img/...`.
- [ ] В логах нет массовых «Пропущен товар …» (единичные — ок, битые товары 1С).
- [ ] `update_remains_*` / отправка заказов **не выполнялись** (они на очереди `celery`,
      которую воркер сейчас не слушает) — это и нужно на пробе.

🛑 Если каталог лёг криво — откат (раздел 6).

---

## 5. Полный режим (маркетплейсы + заказы)

⚠️ **Гейт перед заказами:** в `POST /order` поле `Покупатель` теперь = `"OZON {номер}"` /
`"Wildberries {номер}"` (поля `name_shop` в БД нет → fallback). По нему 1С ищет/создаёт
партнёра и контрагента. **Подтвердить у 1С-разработчика, что это ожидаемое значение,
до включения отправки заказов** — иначе дубли контрагентов.

- [ ] Значение `Покупатель` подтверждено 1С-разработчиком.
- [ ] Вернуть `celery` в очереди:
      ```ini
      CELERYD_OPTS="-Q celery,catalog,images -c 4 -O fair"
      ```
      ```bash
      sudo systemctl daemon-reload && sudo systemctl restart celery
      sudo systemctl start celerybeat     # включить расписание обратно
      ```
- [ ] Прогнать `get_data_1C.delay()` ещё раз и убедиться, что после чанков отрабатывает
      `after_catalog_update` → `update_remains_ozon/wb`, `update_stock_ali` (остатки уходят).
- [ ] Проверить отправку одного-двух тестовых заказов в 1С (контрагент создаётся корректно,
      дублей нет, документ проводится).

---

## 6. Откат (миграций нет — чистый)

```bash
cd /var/www/LECALAPPF
git checkout <прежняя-ветка-из-раздела-0>
.venv/bin/python manage.py collectstatic --noinput
# вернуть старый /etc/systemd/celery.conf (CELERYD_OPTS="--purge") и старый unit
sudo systemctl daemon-reload
sudo systemctl restart celery
sudo systemctl restart gunicorn
sudo systemctl start celerybeat
```

---

## Чеклист коротко
- [ ] prokopov доступен, `BASE_URL_1C_HS` ок, бэкап БД
- [ ] выкатить ветку, `migrate` (no-op), `check`
- [ ] smoke `c1_step1_read` → ПОДТВЕРЖДЁН
- [ ] celery.conf `-Q catalog,images` (проба), unit без purge, beat остановлен
- [ ] прогон каталога → БД/картинки ок
- [ ] подтвердить `Покупатель` у 1С
- [ ] celery.conf `-Q celery,catalog,images`, beat включить
- [ ] проверить остатки на маркетплейсы и пару заказов
