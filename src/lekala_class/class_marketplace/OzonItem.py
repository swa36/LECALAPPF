from abc import abstractmethod
from catalog.models import MarkUpItems
from src.lekala_class.class_marketplace.ozon_dict import *


class OzonItem:
    BRAND_ID = 85
    TYPE_ID = 8229
    CODE_ARTICLE_ID = 7236
    ITEM_TYPE_ID = 8229
    CODE_ITEM_ID = 9048
    CODE_OFFER_ID = 9024
    NAME_ITEM_ID = 4180
    KEYWORDS_ID = 22336
    DESCRIPTION_ID = 4191
    COUNTRY_OF_ORIGIN_ID = 4389
    WARRANTY_ID = 4385
    WEIGHT_ID = 4383
    GROSS_WEIGHT_ID = 4497
    POSITION_ID = 20189
    INSTALLATION_PLACE_ID = 7271
    QUANTITY_ID = 7202
    COLOR_ITEM_ID = 10096
    MATERIAL_ID = 7199
    EQUIPMENT_ID = 4384
    MARK_ID = {'id': 22916, 'complex_id': 100003}

    def __init__(self, product):
        self.product = product
        self.main_img = self._set_main_img()
        self.other_img = [f'https://lpff.ru{i.image.url}' for i in self.product.images.filter(main=False)[:14]]
        self.price = int(self.product.prices.retail_price)
        self.attributes = self._get_additional_attributes()

    def _get_additional_attributes(self):
        return {
            attr.attribute_name.slug_name: attr.value_attribute
            for attr in self.product.additional_attributes.all()
        }

    def _set_main_img(self):
        img = self.product.images.filter(main=True).first()
        return f'https://lpff.ru{img.image.url}' if img else ""

    def create_price(self):
        mark_up = MarkUpItems.objects.last()
        result_price = int(self.price + (mark_up.ozon_mark_up * self.price) / 100)
        return result_price, result_price

    def generate_keywords(self):
        brand = self.attributes.get("mark", "")
        return f"lekalappf;LEKALAPPF бронепленка для {brand}; пленка для {brand}; защитная пленка {brand}"

    def build_attribute(self, attr_id, value, dict_id=None):
        if not value:
            return None  # Ключевой момент
        val = {"value": value}
        if dict_id:
            val["dictionary_value_id"] = dict_id
        return {
            "complex_id": 0,
            "id": attr_id,
            "values": [val]
        }

    def base_attributes(self):
        return [
            self.build_attribute(self.BRAND_ID, "LEKALAPPF", 972205106),
            self.build_attribute(self.CODE_ARTICLE_ID, self.product.article_1C),
            self.build_attribute(self.CODE_ITEM_ID, self.product.article_1C),
            self.build_attribute(self.NAME_ITEM_ID, self.product.name),
            self.build_attribute(self.DESCRIPTION_ID, self.product.description),
            self.build_attribute(self.KEYWORDS_ID, self.generate_keywords()),
            self.build_attribute(self.TYPE_ID, "Пленка защитная для автомобиля", 971053255),
        ]

    def item(self):
        normal_price, _ = self.create_price()
        depth = float(self.attributes.get('length', 0)) * 10
        width = float(self.attributes.get('width', 0)) * 10
        height = float(self.attributes.get('height', 0)) * 10

        # Обработка весов
        weight = self.attributes.get("weight_netto", "")
        gross_weight = self.attributes.get("weight_brutto", "")

        try:
            weight_val = float(weight)
        except (ValueError, TypeError):
            weight_val = 0

        try:
            gross_weight_val = float(gross_weight)
        except (ValueError, TypeError):
            gross_weight_val = 0

        if weight_val == 0:
            weight_val = 3

        # Преобразуем вес к граммам
        weight_grams = weight_val * 1000

        mark = self.attributes.get("mark", "")

        return {
            "attributes": self.set_atribute(),
            "description_category_id": 17028755,
            "complex_attributes": [
                {
                    "id": self.MARK_ID['id'],
                    "complex_id": self.MARK_ID['complex_id'],
                    "values": [{
                        "dictionary_value_id": MARK_DICT.get(mark, 0),
                        "value": mark
                    }]
                }
            ],
            "currency_code": "RUB",
            "dimension_unit": "mm",
            "height": height,
            "width": width,
            "depth": depth,
            "images": self.other_img,
            "images360": [],
            "name": self.product.name,
            "offer_id": str(self.product.code_1C),
            "old_price": "0",
            "price": str(normal_price),
            "primary_image": self.main_img,
            "weight": weight_grams if weight_val else 300,
            "weight_unit": "g",
            "type_id": 971053255
        }

    @abstractmethod
    def set_atribute(self):
        pass


class OzonTape(OzonItem):
    def __init__(self, ozon_data):
        super().__init__(ozon_data)

    def set_atribute(self):
        attrs = self.base_attributes()

        weight = self.attributes.get("weight_netto", "")
        gross_weight = self.attributes.get("weight_brutto", "")

        # Приводим к числу и сравниваем
        try:
            weight_val = float(weight)
        except (ValueError, TypeError):
            weight_val = 0

        try:
            gross_weight_val = float(gross_weight)
        except (ValueError, TypeError):
            gross_weight_val = 0

        # Подмена если один из весов отсутствует или равен 0
        if weight_val == 0 and gross_weight_val > 0:
            weight = gross_weight
        elif gross_weight_val == 0 and weight_val > 0:
            gross_weight = weight

        attrs.extend(filter(None,[
            self.build_attribute(
                self.INSTALLATION_PLACE_ID,
                self.attributes.get("position_install", ""),
                INSTALLATION_PLACE_DICT.get(self.attributes.get("position_install", ""))
            ),
            self.build_attribute(
                self.POSITION_ID,
                self.attributes.get("location_detail", ""),
                POSITION_DICT.get(self.attributes.get("location_detail", ""))
            ),
            self.build_attribute(
                self.COLOR_ITEM_ID,
                self.attributes.get("color", ""),
                COLOR_DICT.get(self.attributes.get("color", "").lower())
            ),
            self.build_attribute(self.MATERIAL_ID, "Полиуретан", 62036),
            self.build_attribute(self.WARRANTY_ID, self.attributes.get("waranty", "")),
            self.build_attribute(self.COUNTRY_OF_ORIGIN_ID, "Россия", 90295),
            self.build_attribute(self.EQUIPMENT_ID, self.attributes.get("equipment", "")),
            self.build_attribute(self.WEIGHT_ID, weight if weight else "300"),
            self.build_attribute(self.GROSS_WEIGHT_ID, gross_weight if gross_weight else "300"),
        ]))
        return attrs
