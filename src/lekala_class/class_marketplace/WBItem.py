from catalog.models import MarkUpItems



class WBItem:
    MAIN_CAT_ID = 8891
    SUB_CAT_ID = 6466
    def __init__(self, prod):
        self.prod = prod
        self.price = int(self.prod.prices.retail_price)
        self.attribs = self._set_attrib()
        self.article = self.prod.article_1C

    def create_price(self):
        mark_up = MarkUpItems.objects.last()
        normal_price = int(self.price + (mark_up.wildberries_mark_up * self.price) / 100)
        return normal_price

    def _set_attrib(self):
        attribs = self.prod.additional_attributes.all()
        return {i.attribute_name.slug_name:i.value_attribute for i in attribs}


    def characteristics(self):
        list_characteristics = [
            {"id": 17596, "value": [self.attribs.get('material', 'Полиуритан')]},
            {"id": 378533, "value": [self.attribs['equipment']]},
            {"id": 14177451, "value": ["Россия"]},
        ]

        return list_characteristics

    def dataItemCard(self):
        if self.attribs.get('material') and self.attribs.get('width') and self.attribs.get('length') and self.attribs.get('equipment') and self.attribs.get('color'):
            list_characteristics = self.characteristics()
            weight = self.attribs.get('weight_netto') or self.attribs.get('weight_brutto') or 0.3
            data = {
                "subjectID": self.SUB_CAT_ID,
                "variants": [
                    {
                        "vendorCode": self.prod.article_1C,
                        "title": self.prod.name[:59],
                        "description": self.prod.description,
                        "brand": "LekalaPPF",
                        "dimensions": {
                            "length": int(self.attribs['length']),
                            "width": int(self.attribs['width']),
                            "height": int(self.attribs['height']),
                            "weightBrutto": float(weight)
                        },
                        "characteristics": list_characteristics,
                    }
                ]
            }
            return data
        else:
            return False
