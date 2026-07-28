import time
from typing import Optional, Dict
import pandas as pd
from celery import shared_task
from django.db.models import Q, F

from src.lekala_class.class_1C.ExChange1C import ExChange1C
from order.models import OrderWB
from src.lekala_class.class_marketplace.WB import WBItemCard, PriceItemWB, StockItemWB, GetOrderWB
from catalog.models import Product, MarkUpItems, Category
from wildberries.models import WBData
from src.lekala_class.class_marketplace.WBItem import WBItem


def exele_wb():
    df = pd.read_excel("src/WBData/wb_data.xlsx", sheet_name="Товары")
    artikuls = df[["Артикул продавца","Наименование", "Артикул WB","Баркод"]]
    records = artikuls.dropna().to_dict(orient="records")
    # Печатаем список
    s=0
    for i in records:
        try:
            p = Product.objects.get(name__contains=i['Наименование'])
            if not hasattr(p, 'wb'):
                print(i)
        except Product.DoesNotExist:
            s+=1
        except Product.MultipleObjectsReturned:
            try:
                p = Product.objects.get(article_1C=i['Артикул продавца'])
            except Product.DoesNotExist:
                print(f'{i['Наименование']} два')
    print(s)



def iter_wb_cards(wb_api, param):
    """Все карточки WB под фильтром param, постранично по курсору."""
    cursor = None
    while True:
        data = wb_api.get_items(param=param, cursor=cursor)
        cards = data.get('cards')
        if cards is None:
            return
        yield data
        cursor_data = data.get('cursor') or {}
        if len(cards) < 100 or 'nmID' not in cursor_data or 'updatedAt' not in cursor_data:
            return
        cursor = {
            "updatedAt": cursor_data['updatedAt'],
            "nmID": cursor_data['nmID'],
            "limit": 100
        }


def set_id_wb(param='all') -> None:
    """Привязывает карточки WB к товарам.

    param задаёт, какие карточки обходить: 'all', 'withoutImg' или 'withImg'.
    Раньше обход был жёстко зашит на 'withoutImg', и карточки, не попавшие под
    этот фильтр, не привязывались никогда, сколько ни запускай.
    """
    wb_api = WBItemCard()
    for page in iter_wb_cards(wb_api, param):
        wb_api.set_id_wb_num(page)


@shared_task
def update_price_wb():
    wb_api = PriceItemWB()
    product_wb = Product.objects.filter(wb__isnull=False).values_list('wb__wb_id', 'prices__retail_price')
    mark_up = MarkUpItems.objects.last()
    list_price = []
    list_discount_wb = []
    for i in product_wb:
        price = wb_api.round_to_nearest_10_custom(i[1] + (mark_up.wildberries_mark_up * i[1]) / 100)
        if price <= 0:
            continue
        if i[0]:
            list_price.append({"nmID": int(i[0]),"price": int(price), "discount": 0})
            list_discount_wb.append({"nmID": int(i[0]), "clubDiscount": 3})
        if len(list_price) > 999:
            wb_api.update_price(data=list_price)
            wb_api.set_price_club_wb(data=list_discount_wb)
            list_price.clear()
            list_discount_wb.clear()
            time.sleep(10)
    if list_price:
        wb_api.update_price(data=list_price)
        wb_api.set_price_club_wb(data=list_discount_wb)



@shared_task
def update_remains_wb():
    print("Start update stock WB")
    wb_api = StockItemWB()
    product_wb = Product.objects.filter(wb__isnull=False).values_list('wb__wb_barcode', 'stock')
    list_stock = []
    for i in product_wb:
        if len(list_stock) > 999:
            wb_api.update_remains(data=list_stock, save_to_file=False)
            list_stock.clear()
        if i[0] and i[0] != "2000000046747":
            list_stock.append({"sku": str(i[0]), "amount": int(i[1]) if wb_api.work_time_wb() else 0})
    if list_stock:
        wb_api.update_remains(data=list_stock, save_to_file=False)
    print("End update stock WB")

@shared_task
def get_new_order_wb():
    wb_api = GetOrderWB()
    wb_order = wb_api.get_new_order()
    for o in wb_order['orders']:
        if not OrderWB.objects.filter(number_WB=o['id']).exists():
            price = o['convertedPrice']/100
            try:
                prod = Product.objects.get(article_1C=o['article'])
            except:
                prod = None
            number_1c = wb_api.number_to_1c()
            OrderWB.objects.create(
                number_WB=o['id'],
                number_1C=number_1c,
                product=prod,
                price = price,
            )
            print('New order create WB')
    return

def candidates_for_wb():
    """Товары без карточки WB, которых можно туда завести."""
    exclude_cat = Category.objects.filter(
        name='Инструмент и оборудование для нанесения плёнок'
    ).first()
    exclude_ids = [i.id for i in exclude_cat.get_family()] if exclude_cat else []
    return Product.objects.filter(
        Q(wb__isnull=True) & Q(is_archive=False)
        & ~Q(category__id__in=exclude_ids)
    )


def existing_vendor_codes_wb(wb_api=None):
    """vendorCode всех карточек на WB — актуальных и в корзине.

    WB отвергает создание карточки с занятым артикулом ошибкой
    "the specified card's vendor code is used in other cards". Так бывает, когда
    карточка на WB есть, а связки WBData в базе нет: тогда товар выглядит как
    «без карточки». Собранные коды позволяют не отправлять заведомо отбойные.
    """
    wb_api = wb_api or WBItemCard()
    codes = set()

    cursor = None
    while True:
        data = wb_api.get_items(param='all', cursor=cursor)
        cards = data.get('cards')
        if cards is None:
            return None
        codes.update(card['vendorCode'] for card in cards if card.get('vendorCode'))
        cursor_data = data.get('cursor') or {}
        if len(cards) < 100 or 'nmID' not in cursor_data or 'updatedAt' not in cursor_data:
            break
        cursor = {
            'updatedAt': cursor_data['updatedAt'],
            'nmID': cursor_data['nmID'],
            'limit': 100,
        }

    cursor = None
    while True:
        data = wb_api.get_trash(cursor=cursor)
        cards = data.get('cards') or []
        codes.update(card['vendorCode'] for card in cards if card.get('vendorCode'))
        cursor_data = data.get('cursor') or {}
        if len(cards) < 100 or 'nmID' not in cursor_data or 'trashedAt' not in cursor_data:
            break
        cursor = {
            'trashedAt': cursor_data['trashedAt'],
            'nmID': cursor_data['nmID'],
            'limit': 100,
        }

    return codes


def add_new_item_wb(dry_run=False, limit=None, report=None):
    """Заводит карточки на WB для товаров, которых там ещё нет.

    Товар пропускается, если у него не заполнены атрибуты, обязательные для
    карточки (material, width, length, equipment, color), нет розничной цены
    или его артикул уже занят карточкой на WB. Такие собираются в report,
    если он передан.
    """
    wb_api = WBItemCard()
    taken_codes = existing_vendor_codes_wb(wb_api)
    if taken_codes is None:
        print('WB не вернул список карточек — заведение отменено, иначе полезли бы дубли')
        return 0

    product_not_wb = candidates_for_wb()
    if limit:
        product_not_wb = product_not_wb[:limit]

    sent = 0
    batch = []
    for item in product_not_wb:
        if item.article_1C in taken_codes:
            if report is not None:
                report.setdefault('taken', []).append(item)
            continue
        # Если пакет заполнен, отправляем его
        if len(batch) >= 1:
            if not dry_run:
                wb_api.post_items(data=batch)
                time.sleep(5)
            sent += len(batch)
            batch.clear()  # Очистка пакета после отправки
        # Преобразование элемента в формат для API
        try:
            item_data = WBItem(item).dataItemCard()
        except Exception as exc:
            if report is not None:
                report.setdefault('skipped', []).append((item, str(exc)))
            continue
        if item_data:
            batch.append(item_data)
        elif report is not None:
            report.setdefault('skipped', []).append((item, 'не хватает атрибутов'))
    # Отправка оставшихся элементов, если они есть
    if batch:
        if not dry_run:
            wb_api.post_items(data=batch)
        sent += len(batch)

    if report is not None:
        report['sent'] = sent
    return sent

def update_item_wb(data):
    batch = []
    wb_api = WBItemCard()
    for i in data.get("cards", None):
        try:
            item = Product.objects.get(article_1C=i.get('vendorCode'))
            item_data = WBItem(item).dataForUpdateItemCard(i)
            if item_data:
                batch.append(item_data)
        except Exception as e:
            print(i.get('vendorCode'))
            continue
    wb_api.update_item(data=batch)
    time.sleep(10)


@shared_task
def update_vendor_code_wb(dry_run=False):
    """Приводит vendorCode на WB к article_1C из 1С.

    Карточка ищется по nmID (он неизменен), поэтому связка не рвётся, даже
    когда артикул уже разъехался. v2/cards/update перезаписывает карточку
    целиком, поэтому берём её из v2/get/cards/list как есть и правим только
    vendorCode.
    """
    mismatched = {
        wb_id: article
        for wb_id, article in Product.objects.filter(wb__isnull=False)
        .exclude(article_1C=F('wb__offer_id'))
        .values_list('wb__wb_id', 'article_1C')
        if wb_id
    }
    if not mismatched:
        print('Расхождений article_1C и offer_id нет')
        return

    print(f'Артикулов к обновлению: {len(mismatched)}')

    wb_api = WBItemCard()
    batch = []
    cursor = None
    while True:
        data = wb_api.get_items(param='all', cursor=cursor)
        cards = data.get('cards') or []
        for card in cards:
            new_code = mismatched.get(card.get('nmID'))
            if not new_code:
                continue
            print(
                f"nmID {card['nmID']}: {card['vendorCode']} -> {new_code}\n"
                f"    карточка WB: {card.get('title')}\n"
                f"    товар в БД : {Product.objects.get(wb__wb_id=card['nmID']).name}"
            )
            payload = {
                key: value
                for key, value in card.items()
                if key not in ('createdAt', 'updatedAt')
            }
            payload['vendorCode'] = new_code
            batch.append(payload)

        cursor_data = data.get('cursor') or {}
        if len(cards) < 100 or 'nmID' not in cursor_data or 'updatedAt' not in cursor_data:
            break
        cursor = {
            'updatedAt': cursor_data['updatedAt'],
            'nmID': cursor_data['nmID'],
            'limit': 100,
        }

    not_found = set(mismatched) - {card['nmID'] for card in batch}
    if not_found:
        print(f'Карточки не найдены на WB, nmID: {sorted(not_found)}')

    if not batch:
        print('Нечего отправлять')
        return

    if dry_run:
        print(f'dry_run: на WB ничего не отправлено, в батче карточек {len(batch)}')
        return

    for start in range(0, len(batch), 100):
        chunk = batch[start:start + 100]
        response = wb_api.update_item(data=chunk)
        if isinstance(response, dict) and response.get('error'):
            print(f"WB вернул ошибку: {response.get('errorText')}")
            continue
        for card in chunk:
            WBData.objects.filter(wb_id=card['nmID']).update(offer_id=card['vendorCode'])
        # лимит метода — 10 запросов в минуту
        time.sleep(7)

    print(
        'Готово. Изменения на WB применяются до 30 минут; '
        'непрошедшие карточки смотри в v2/cards/error/list'
    )


def get_all_card(next_cursor:Optional[Dict]=None):
    wb_api = WBItemCard()
    if next_cursor:
        data = wb_api.get_items(param='all',cursor=next_cursor)
    else:
        data = wb_api.get_items(param='all')
    update_item_wb(data)
    if 'nmID' in  data['cursor'] and 'updatedAt' in data['cursor']:
        next_cursor = {
            "updatedAt": data['cursor']['updatedAt'],
            "nmID": data['cursor']['nmID'],
            "limit": 100
        }
        get_all_card(next_cursor)




def sent_img_wb(param='withoutImg', dry_run=False, report=None):
    """Заливает изображения на карточки WB.

    param задаёт, какие карточки обходить: 'withoutImg' (по умолчанию — им
    картинки и нужны), 'all' или 'withImg'. Раньше бралась только первая
    страница выдачи, то есть максимум 100 карточек.
    """
    wb_api = WBItemCard()
    sent = 0
    for page in iter_wb_cards(wb_api, param):
        for i in page['cards']:
            code = i.get('vendorCode')
            try:
                prod = Product.objects.get(article_1C=code)
            except Product.DoesNotExist:
                if report is not None:
                    report.setdefault('skipped', []).append((code, 'товара нет в базе'))
                continue
            except Product.MultipleObjectsReturned:
                if report is not None:
                    report.setdefault('skipped', []).append((code, 'артикул задублирован в 1С'))
                continue

            if not prod.images.exists():
                if report is not None:
                    report.setdefault('skipped', []).append((code, 'нет изображений на сайте'))
                continue

            print(f'{code} {prod.name[:45]}')
            if not dry_run:
                try:
                    wb_api.post_img(prod)
                except Exception as exc:
                    if report is not None:
                        report.setdefault('skipped', []).append((code, f'ошибка отправки: {exc}'))
                    continue
            sent += 1

    if report is not None:
        report['sent'] = sent
    return sent

@shared_task
def sent_img_video(id=None):
    wb_api = WBItemCard()
    if id:
        print('Обновялем фото на Wildberies')
        products_wb = Product.objects.filter(id=id)
    else:
        products_wb = Product.objects.filter(wb__isnull=False)
    for p in products_wb:
        print(p.wb.wb_id)
        wb_api.post_img(p)


