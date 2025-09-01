from datetime import datetime
import json
from pathlib import Path
import shutil
import lekala_ppf.settings as settings
from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.core.files.base import ContentFile
from catalog.models import Product, Images
import base64
import requests



class ExChange1C:
    BASE_URL = settings.BASE_URL_1C

    def __init__(self):
        self.default_params = {
            '$format': 'application/json;odata=nometadata'
        }

        # Авторизация
        self.auth = HTTPBasicAuth(
            settings.LOGIN_1C,
            settings.PASSWORD_1C
        )

        # Сессия с retry
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _make_request(self, method, endpoint, params=None):
        url = self.BASE_URL + endpoint
        merged_params = {**self.default_params, **(params or {})}
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=merged_params,
                auth=self.auth,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка запроса к 1С: {url}\n{e}")
            return {"value": []}

    def get_catalog(self):
        endpoint = 'Catalog_Номенклатура?$filter=IsFolder eq false and DeletionMark eq false'
        fields = [
            'Ref_Key', 'Parent_Key', 'DataVersion', 'IsFolder', 'Code', 'Артикул',
            'ВесЧислитель', 'Description', 'Описание', 'ФайлКартинки_Key', 'ДополнительныеРеквизиты'
        ]
        params = {
            '$select': ','.join(fields),
        }
        result = self._make_request('GET', endpoint, params=params)
        self._save_to_json(result, 'data_catalog.json')
        return result

    def get_category(self):
        endpoint = 'Catalog_Номенклатура?$filter=IsFolder eq true and DeletionMark eq false'
        fields = [
            'Ref_Key', 'Parent_Key', 'Description'
        ]
        params = {
            '$select': ','.join(fields),
        }
        result = self._make_request('GET', endpoint, params=params)
        return result

    def get_name_additional_attributes(self):
        endpoint = 'ChartOfCharacteristicTypes_ДополнительныеРеквизитыИСведения'
        fields = [
            'Ref_Key', 'Description'
        ]
        params = {
            '$select': ','.join(fields)
        }
        return self._make_request('GET', endpoint, params=params)

    def get_additional_attributes(self):
        endpoint = 'Catalog_Номенклатура_ДополнительныеРеквизиты'
        fields = [
            'Ref_Key', 'Значение'
        ]
        params = {
            '$select': ','.join(fields)
        }
        return self._make_request('GET', endpoint, params=params)

    def get_type_price(self):
        endpoint = 'Catalog_ВидыЦен'
        fields = [
            'Ref_Key', 'Description'
        ]
        params = {
            '$select': ','.join(fields)
        }
        return self._make_request('GET', endpoint, params=params)

    def get_price(self):
        endpoint = 'InformationRegister_ЦеныНоменклатуры_RecordType'
        fields = ['Period', 'Номенклатура_Key', 'ВидЦены_Key', 'Цена']
        params = {
            '$select': ','.join(fields)
        }
        result =  self._make_request('GET', endpoint, params=params)
        self._save_to_json(result, 'data_price.json')
        return result

    def get_reserv_item(self):
        endpoint=f"InformationRegister_СостоянияЗаказовКлиентов"
        fields=['Заказ', 'Состояние']
        params = {
            '$orderby':'ДатаСобытия desc',
            '$select': ','.join(fields),
            '$top':100

        }
        return self._make_request('GET', endpoint, params=params)

    def get_stock(self):
        endpoint = 'AccumulationRegister_ЗапасыИПотребности_RecordType'
        fields = ['Номенклатура_Key', 'ВНаличии', 'RecordType']
        params = {
            '$select': ','.join(fields)
        }
        result =  self._make_request('GET', endpoint, params=params)
        self._save_to_json(result, 'data_stock.json')
        return
    

    def get_img(self, id_item):
        try:
            product = Product.objects.get(uuid_1C=id_item)
            id_main_img = str(product.main_img_uuid)
        except Product.DoesNotExist:
            print(f"❌ Продукт с id={id_item} не найден")
            return

        # Получение списка файлов, связанных с товаром
        try:
            response = requests.get(
                f"{self.BASE_URL}Catalog_НоменклатураПрисоединенныеФайлы?"
                f"$filter=ВладелецФайла_Key eq guid'{id_item}' and DeletionMark eq false&"
                f"$select=Ref_Key&$format=application/json;odata=nometadata",
                auth=self.auth,
                timeout=10
            )
            response.raise_for_status()
            file_records = response.json().get('value', [])
        except requests.RequestException as e:
            print(f"❌ Ошибка при получении списка файлов: {e}")
            return

        if not file_records:
            print(f"⚠️ Нет изображений в 1С для товара {product.name}")
            return
        
        today = datetime.now().strftime("%d%m%y")
        pending_images = []
        sequence_number = 1

        for file_info in file_records:
            file_id = file_info.get('Ref_Key')
            is_main = (file_id == id_main_img)
            filename = f"main_{today}.jpg" if is_main else f"{sequence_number}_{today}.jpg"

            base64_data = self._fetch_image_base64(file_id)
            if not base64_data:
                print(f"⚠️ Не удалось получить изображение для файла {file_id}, обновление отменено.")
                return

            try:
                image_bytes = base64.b64decode(base64_data)
            except Exception as e:
                print(f"⚠️ Ошибка декодирования base64 для файла {file_id}: {e}, обновление отменено.")
                return

            pending_images.append({
                'filename': filename,
                'main': is_main,
                'bytes': image_bytes
            })

            if not is_main:
                sequence_number += 1

        # ✅ Удаляем старые изображения и их файлы
        product.images.all().delete()
        media_path = settings.BASE_DIR / 'media' / 'img' / product.code_1C
        if media_path.exists() and media_path.is_dir():
            try:
                shutil.rmtree(media_path)
                print(f"🗑️ Удалена папка со всеми изображениями: {media_path}")
            except Exception as e:
                print(f"❌ Ошибка при удалении папки: {e}")
        else:
            print(f"⚠️ Папка {media_path} не найдена")
                
        # ✅ Сохраняем новые изображения
        for image in pending_images:
            img_obj = Images.objects.create(
                product=product,
                filename=image['filename'],
                main=image['main']
            )
            img_obj.image.save(image['filename'], ContentFile(image['bytes']), save=True)
            print(f"✅ Сохранено изображение: {image['filename']}")

        print(f"✅ Успешно обновлены изображения для товара {product.name}")



    def _fetch_image_base64(self, file_id):
        """Пробует получить base64 из двух возможных источников."""
        try:
            # Старое хранилище
            url_old = (
                f"{self.BASE_URL}"
                f"InformationRegister_УдалитьДвоичныеДанныеФайлов(Файл='{file_id}', "
                f"Файл_Type='StandardODATA.Catalog_НоменклатураПрисоединенныеФайлы')"
                f"?$select=ДвоичныеДанныеФайла_Base64Data&$format=application/json;odata=nometadata"
            )
            response = requests.get(url_old, auth=self.auth, timeout=10)
            if response.ok:
                return response.json().get('ДвоичныеДанныеФайла_Base64Data')
        except Exception as e:
            print(f"⚠️ Ошибка при попытке получить файл из старого хранилища: {e}")

        try:
            # Новое хранилище
            url_new = (
                f"{self.BASE_URL}"
                f"InformationRegister_ХранилищеФайлов(Файл='{file_id}', Файл_Type='StandardODATA.Catalog_НоменклатураПрисоединенныеФайлы')/"
                f"ХранилищеДвоичныхДанных"
                f"?$select=ДвоичныеДанные_Base64Data&$format=application/json;odata=nometadata"
            )
            response = requests.get(url_new, auth=self.auth, timeout=10)
            if response.ok:
                return response.json().get('ДвоичныеДанные_Base64Data')
        except Exception as e:
            print(f"⚠️ Ошибка при попытке получить файл из нового хранилища: {e}")

        return None

    def _save_to_json(self, data: dict, filename: str):
        output_dir = Path("json/data_1C")
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    


