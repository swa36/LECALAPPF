from pathlib import Path
import re, os, shutil
from celery import shared_task
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

@shared_task
def get_data_chunck(payload):
    data_catalog = payload['catalog']
    data1C = GetData1C()
    data1C.set_catalog_data_stock(data_catalog)


@shared_task
def get_data_1C():
    print("START UPDATE ALL")
    data1C = GetData1C()
    data_catalog = data1C.get_catalog()['value']
    data1C.get_price()
    data1C.get_stock()
    data1C.set_name_attribute()
    data1C.set_type_price()
    data1C.set_category_catalog()
    chunk_size = len(data_catalog) // 5 + (1 if len(data_catalog) % 5 else 0)
    chunks_data_catalog = [data_catalog[i:i + chunk_size] for i in range(0, len(data_catalog), chunk_size)]
    for chunk in chunks_data_catalog:
        get_data_chunck({
            'catalog': chunk,
        })
    update_remains_ozon.delay()
    update_remains_wb.delay()
    # sent_stock_ya.delay()
    update_stock_ali.delay()
    




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