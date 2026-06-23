import base64
import shutil
from datetime import datetime
from pathlib import Path

import requests
from catalog.models import Images, Product
from django.conf import settings
from django.core.files.base import ContentFile
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry


class ExChange1C:
    BASE_URL = settings.BASE_URL_1C_HS.rstrip("/") + "/"

    def __init__(self):
        self.auth = HTTPBasicAuth(settings.LOGIN_1C, settings.PASSWORD_1C)

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({"Accept-Encoding": "gzip"})

    def _make_request(self, method, endpoint, params=None, json_body=None):
        url = self.BASE_URL + endpoint.lstrip("/")
        request_kwargs = {
            "method": method,
            "url": url,
            "params": params,
            "auth": self.auth,
            "timeout": 10,
        }
        if json_body is not None:
            request_kwargs["json"] = json_body

        try:
            response = self.session.request(**request_kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            print(f"Ошибка запроса к 1С: {url}\n{exc}")
            return {"value": []}

    def get_products(self, page=1, page_size=200):
        return self._make_request(
            "GET",
            "products",
            params={"page": page, "page_size": page_size},
        )

    def get_all_products(self, page_size=200):
        first_page = self.get_products(page=1, page_size=page_size)
        items = list(first_page.get("items", []))
        pages = int(first_page.get("pages") or 1)

        for page in range(2, pages + 1):
            data = self.get_products(page=page, page_size=page_size)
            items.extend(data.get("items", []))

        return items

    def get_category(self):
        return self._make_request("GET", "categories")

    def get_name_additional_attributes(self):
        return self._make_request("GET", "attributes")

    def get_type_price(self):
        return self._make_request("GET", "pricetypes")

    def get_orders_in_shipping(self):
        return self._make_request("GET", "orders-in-shipping")

    def get_img(self, id_item):
        try:
            product = Product.objects.get(uuid_1C=id_item)
        except Product.DoesNotExist:
            print(f"Продукт с id={id_item} не найден")
            return

        payload = self._make_request("GET", f"product-images/{id_item}")
        image_records = payload.get("images", [])
        if not image_records:
            print(f"Нет изображений в 1С для товара {product.name}")
            return

        today = datetime.now().strftime("%d%m%y_%H%M")
        pending_images = []
        sequence_number = 1

        for image_info in image_records:
            is_main = bool(image_info.get("is_main"))
            filename = f"main_{today}.jpg" if is_main else f"{sequence_number}_{today}.jpg"
            base64_data = image_info.get("data_base64")
            if not base64_data:
                print("Не удалось получить изображение, обновление отменено.")
                return

            try:
                image_bytes = base64.b64decode(base64_data)
            except Exception as exc:
                print(f"Ошибка декодирования base64: {exc}, обновление отменено.")
                return

            pending_images.append(
                {
                    "filename": filename,
                    "main": is_main,
                    "bytes": image_bytes,
                }
            )
            if not is_main:
                sequence_number += 1

        product.images.all().delete()
        media_path = Path(settings.MEDIA_ROOT) / "img" / product.code_1C
        if media_path.exists() and media_path.is_dir():
            try:
                shutil.rmtree(media_path)
            except Exception as exc:
                print(f"Ошибка при удалении папки изображений: {exc}")

        for image in pending_images:
            img_obj = Images.objects.create(
                product=product,
                filename=image["filename"],
                main=image["main"],
            )
            img_obj.image.save(image["filename"], ContentFile(image["bytes"]), save=True)

        if hasattr(product, "ozon"):
            from ozon.tasks import update_img_ozon as sent_img_ozon

            sent_img_ozon.delay(id=product.id)
        if hasattr(product, "wb"):
            from wildberries.tasks import sent_img_video as sent_img_wb

            sent_img_wb.delay(id=product.id)
