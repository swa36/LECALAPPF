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
            'Ref_Key', 'DataVersion', 'IsFolder', 'Code', 'Артикул',
            'ВесЧислитель', 'Description', 'Описание', 'ФайлКартинки_Key', 'ДополнительныеРеквизиты'
        ]
        params = {
            '$select': ','.join(fields),
        }
        return self._make_request('GET', endpoint, params=params)

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
        return self._make_request('GET', endpoint, params=params)

    def get_stock(self):
        endpoint = 'AccumulationRegister_ЗапасыИПотребности_RecordType'
        fields = ['Номенклатура_Key', 'ВНаличии', 'RecordType']
        params = {
            '$select': ','.join(fields)
        }
        return self._make_request('GET', endpoint, params=params)

    from django.core.files.base import ContentFile
    from pathlib import Path
    from catalog.models import Product, Images
    import base64
    import requests

    def get_img(self, id_item, id_main_img):
        try:
            product = Product.objects.get(id=id_item)
        except Product.DoesNotExist:
            print(f"❌ Продукт с id={id_item} не найден")
            return

        # Получение списка файлов из 1С
        try:
            response = requests.get(
                f"{self.BASE_URL}InformationRegister_СведенияОФайлах?"
                f"$filter=ВладелецФайла eq cast(guid'{id_item}', 'Catalog_Номенклатура')&"
                f"$select=Файл&$format=application/json;odata=nometadata",
                auth=self.auth,
                timeout=10
            )
            response.raise_for_status()
            file_records = response.json().get('value', [])
        except requests.RequestException as e:
            print(f"❌ Ошибка при получении списка файлов: {e}")
            return

        actual_filenames = set()

        for idx, file_info in enumerate(file_records):
            file_id = file_info.get('Файл')
            is_main = (file_id == id_main_img)
            filename = "main.jpg" if is_main else f"{idx}.jpg"
            actual_filenames.add(filename)

            base64_data = self._fetch_image_base64(file_id)
            if not base64_data:
                print(f"⚠️ Не удалось получить изображение для файла {file_id}")
                continue

            try:
                image_bytes = base64.b64decode(base64_data)
            except Exception as e:
                print(f"⚠️ Ошибка декодирования base64: {e}")
                continue

            img_obj, created = Images.objects.get_or_create(
                product=product,
                filename=filename,
                defaults={'main': is_main}
            )

            if not created:
                img_obj.image.delete(save=False)

            img_obj.image.save(filename, ContentFile(image_bytes), save=False)
            img_obj.main = is_main
            img_obj.filename = filename
            img_obj.save(update_fields=['image', 'main', 'filename'])

            print("✅", "Создана" if created else "Обновлена", filename)

        # Удаление устаревших изображений, не вернувшихся из 1С
        Images.objects.filter(product=product).exclude(filename__in=actual_filenames).delete()

        print("✅ Загрузка и синхронизация изображений завершена")

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
