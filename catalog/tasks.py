from datetime import datetime
from pathlib import Path
import re, os, shutil
from celery import chord, group, shared_task
from django.conf import settings
from django.db.models import Q
from src.lekala_class.class_1C.ExChange1C import ExChange1C
from src.lekala_class.class_1C.GetData1C import GetData1C
from catalog.models import Product, Images
from ozon.tasks import update_remains_ozon
from wildberries.tasks import update_remains_wb
from yamarket.tasks import sent_stock_ya
from aliexpress.tasks import update_stock_ali
from django.core.files import File


@shared_task(acks_late=True)
def update_product_images(uuid):
    ExChange1C().get_img(uuid)

@shared_task(acks_late=True)
def process_catalog_chunk(chunk):
    GetData1C().set_catalog_data_stock(chunk, async_images=True)


@shared_task
def after_catalog_update(results=None):
    # update_remains_ozon.delay()
    update_remains_wb.delay()
    # sent_stock_ya.delay()
    update_stock_ali.delay()


@shared_task
def archive_missing_products(api_uuids):
    """Ставит и снимает метку «архив» по составу выгрузки 1С.

    Товар, перенесённый в 1С в «Удалено(архив)», перестаёт приходить в
    /products, но на сайте остаётся с замороженным остатком и продолжает
    продаваться. Помечаем его и обнуляем остаток: дальше штатные задачи
    разнесут ноль на WB/Ozon/Ali, из фидов Avito и Ali товар выпадет по метке,
    а карточки WB переносятся в корзину командой trash_archived_wb.

    Вернули товар из архива в 1С — метка снимается, остаток приезжает из
    выгрузки сам.
    """
    total = Product.objects.count()
    if not api_uuids or (total and len(api_uuids) < total * 0.5):
        print(
            f"Выгрузка 1С подозрительно мала ({len(api_uuids)} против {total} в БД) — "
            "простановка метки «архив» пропущена, чтобы не снять с продажи весь каталог"
        )
        return 0

    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    missing = Product.objects.exclude(uuid_1C__in=api_uuids).filter(
        Q(is_archive=False) | Q(stock__gt=0)
    )
    rows = list(missing.values_list("article_1C", "name", "stock"))
    archived = missing.update(is_archive=True, stock=0)

    returned_qs = Product.objects.filter(uuid_1C__in=api_uuids, is_archive=True)
    returned_rows = list(returned_qs.values_list("article_1C", "name"))
    returned = returned_qs.update(is_archive=False)

    if rows or returned_rows:
        with open("logs/archived_1c.log", "a", encoding="utf-8") as log_file:
            for article, name, stock in rows:
                log_file.write(f"{timestamp}\tАРХИВ\t{article}\t{name}\tбыл остаток: {stock}\n")
            for article, name in returned_rows:
                log_file.write(f"{timestamp}\tВОЗВРАТ\t{article}\t{name}\n")

    if archived:
        print(f"Нет в выгрузке 1С — помечено архивом и снято с продажи: {archived}")
    if returned:
        print(f"Вернулись в выгрузку 1С — метка «архив» снята: {returned}")
    return archived


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
    archive_missing_products([item["ref_key"] for item in items])
    size = settings.CATALOG_CHUNK_SIZE
    chunks = [items[i:i + size] for i in range(0, len(items), size)]
    header = [process_catalog_chunk.s(chunk) for chunk in chunks]
    chord(group(header))(after_catalog_update.s())
    




def test_get_img():
    products_without_img = Product.objects.filter(Q(ozon__isnull=True) & Q(prices__retail_price__gt = 0) & Q(
        stock__gt=0))
    print(products_without_img.count())
    c = ExChange1C()
    for product in products_without_img:
        print(f'{product.name} {product.code_1C} uuid {product.uuid_1C} id_img {product.main_img_uuid}')
        c.get_img(id_item=product.uuid_1C)


def extract_number(filename):
    match = re.search(r'(\d+)', filename)
    return int(match.group(1)) if match else float('inf')  # inf для нерелевантных



def get_img_1C():
    data_1c=ExChange1C()
    product = Product.objects.filter(wb__isnull=False, name__icontains='Бронеплёнка на камер')
    for i in product:
        data_1c.get_img(i.uuid_1C)

def add_suffix_to_image_paths(suffix: str):
    # Получаем все записи с заполненным полем image
    images = Images.objects.exclude(image='')
    
    for img in images:
        # Получаем текущее полное имя файла
        current_path = img.image.name  # например: img/ABC123/main.jpg
        
        # Разделяем путь на директорию и имя файла
        dir_name, file_name = os.path.split(current_path)
        
        # Добавляем суффикс перед расширением
        name_without_ext, ext = os.path.splitext(file_name)
        new_file_name = f"{name_without_ext}{suffix}{ext}"
        
        # Формируем новый путь
        new_path = os.path.join(dir_name, new_file_name)
        
        # Обновляем поле image (Django сам скопирует файл, если нужно)
        img.image.name = new_path
        
        # Также обновляем поле filename, если оно должно отражать новое имя
        img.filename = new_file_name
        
        # Сохраняем изменения
        img.save(update_fields=['image', 'filename'])
        
        print(f"Обновлено: {current_path} → {new_path}")

def rename():
    for img in Images.objects.all():
        old_path = img.image.file.path
        new_path = os.path.join(
            os.path.dirname(old_path),
            img.filename
        )
        
        if os.path.exists(old_path):
            shutil.move(old_path, new_path)
            print(f"Перемещено: {old_path} → {new_path}")
        else:
            print(f"!Файл не найден: {old_path}")


def rollback_suffix():
    for img in Images.objects.all():
        if '_v2' in img.filename:
            # Удаляем суффикс из filename
            new_filename = img.filename.replace('_v2', '')
            # Формируем старый путь
            old_path = os.path.join(
                os.path.dirname(img.image.name),
                new_filename
            )
            # Обновляем поля
            img.image.name = old_path
            img.filename = new_filename
            img.save(update_fields=['image', 'filename'])
            print(f"Откат: {img.image.name} → {old_path}")
            
def move_files_with_suffix(suffix: str):
    for img in Images.objects.all():
        # Получаем физический путь к файлу через .path (не .file.path!)
        old_path = img.image.path
        
        # Если файл не существует — пропускаем
        if not os.path.exists(old_path):
            print(f"Файл не найден (пропуск): {old_path}")
            continue

        # Разбираем путь на директорию и имя
        dir_name = os.path.dirname(old_path)
        file_name = os.path.basename(old_path)
        
        # Создаём новое имя с суффиксом
        name_without_ext, ext = os.path.splitext(file_name)
        new_filename = f"{name_without_ext}{suffix}{ext}"
        new_path = os.path.join(dir_name, new_filename)

        try:
            # Перемещаем файл на диске
            shutil.move(old_path, new_path)
            print(f"Перемещено: {old_path} → {new_path}")

            # Обновляем поля в БД
            img.image.name = os.path.join(
                os.path.dirname(img.image.name),
                new_filename
            )
            img.filename = new_filename
            img.save(update_fields=['image', 'filename'])
            
        except Exception as e:
            print(f"Ошибка при обработке {old_path}: {e}")
