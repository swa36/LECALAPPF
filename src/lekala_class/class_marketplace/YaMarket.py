from django.db.models import Q, Count
from src.lekala_class.class_marketplace.YaMarketApi import YaMarketApi
from catalog.models import Product, MarkUpItems, Category


class YaMarket(YaMarketApi):
    def __init__(self):
        self.mark_up = MarkUpItems.objects.last().yandex_mark_up
        self.categories_out = self._get_category_ids("Готовые лекала для оклейки")
        self.categories_in = self._get_category_ids("Защитное стекло экранов мультимедиа, приборных панелей, климат-контроля")
        self.categories_moto = self._get_category_ids("Лекала для оклейки мотоциклов")
        self.excluded_categories = self.categories_out + self.categories_in + self.categories_moto
        self.products = Product.objects.annotate(image_count=Count('images')).filter(
            Q(category__in=self.excluded_categories),
            Q(prices__retail_price__gt=0),
            Q(image_count__gt=0)
        ).prefetch_related("images", "additional_attributes__attribute_name")
        super().__init__()

    def _get_category_ids(self, name):
        try:
            return [cat.id for cat in Category.objects.get(name=name).get_family()]
        except Category.DoesNotExist:
            return []

    def post_item_data(self):
        data = []
        for product in self.products:
            attrib = {
                attr.attribute_name.slug_name: attr.value_attribute
                for attr in product.additional_attributes.all()
            }

            price_with_markup = round(product.prices.retail_price + (self.mark_up * product.prices.retail_price) / 100, 2)
            weight = attrib.get("weight_netto") or attrib.get("weight_brutto", 0)
            if weight:
                weight = float(weight)
            else:
                weight = 0.3
            offer = {
                "offerId": product.code_1C,
                "basicPrice": {"value": int(price_with_markup), "currencyId": "RUR"},
                "cofinancePrice": {"value": int(price_with_markup), "currencyId": "RUR"},
                "purchasePrice": {"value": int(price_with_markup), "currencyId": "RUR"},
                "description": product.description,
                "marketCategoryId": 71665598 if product.category.get_root().name in ['Готовые лекала для оклейки',
                                                                                   'Лекала для '
                                                                                                        'оклейки '
                                                                                                        'мотоциклов']
                else 71439214,
                "name": product.name,
                "parameterValues": self.get_param_item(product, attrib),
                "pictures": [f'http://lpff.ru{i.image.url}' for i in product.images.all().order_by('-main')],
                "vendor": "LekalaPPF",
                "vendorCode": product.article_1C,
                "weightDimensions": {
                    "length": attrib.get("length", 0),
                    "width": attrib.get("width", 0),
                    "height": attrib.get("height", 0),
                    "weight": weight,
                },
            }
            if len(data) > 30:
                self.post_new_item(data)
                data.clear()
            data.append({
                "offer": offer,
            })
        if data:
            self.post_new_item(data)
        return

    def get_param_item(self, product, attributes):
        param = [
            {"parameterId": 23679910, "unitId": 8, "value": attributes.get("width", 0)},
            {"parameterId": 23674610, "unitId": 8, "value": attributes.get("length", 0)},
        ]

        coverage_raw = attributes.get("сoverage_1", "").strip().casefold()
        glanc_set = {"глняцевое", "глянцвое", "глянцевая", "глянцевый", "гляцевое", "гляянцевое"}
        mat_set = {"матовое"}

        if coverage_raw in glanc_set:
            param.append({"parameterId": 27142653, "valueId": 28735970, "value": "глянцевая"})
        elif coverage_raw in mat_set:
            param.append({"parameterId": 27142653, "valueId": 28735969, "value": "матовая"})

        root_category = product.category.get_root().name

        if root_category in {"Готовые лекала для оклейки", "Лекала для оклейки мотоциклов"}:
            param.extend([
                {"parameterId": 21194330, "valueId": 32806010, "value": "пленка"},
                {"parameterId": 27142875, "valueId": 28659262, "value": "снаружи"},
            ])
        elif root_category == "Защитное стекло экранов мультимедиа, приборных панелей, климат-контроля":
            param.extend([
                {"parameterId": 21194330, "valueId": 60512682, "value": "защитные пленки салона автомобиля"},
                {"parameterId": 17352854, "valueId": 17362364, "value": "полиуретановая"},
                {"parameterId": 37729570, "valueId": 50450433, "value": "прозрачная"},
            ])
            if attributes.get("thickness"):
                param.append({"parameterId": 23685230, "value": attributes["thickness"]})

        return param

    def sent_stock_market(self):
        data = []
        for f in self.products:
            if len(data) > 1999:
                self.sent_stock(data)
                data.clear()
            data.append(
                {
                    'sku':f.code_1C,
                    'items':[{'count':f.stock}]
                }
            )
        if data:
            self.sent_stock(data)
        return
