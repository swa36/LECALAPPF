from catalog.models import MarkUpItems

# Характеристика «ТНВЭД» предмета 6466. Код Ozon (3909509008) WB для этого
# предмета не принимает — допустимые коды отдаёт v2/directory/tnved?subjectID=6466.
TNVED_CHARC_ID = 15000001
TNVED_CODE = '3919900000'

# Поля, которые принимает v2/cards/update. Остальное из v2/get/cards/list
# (imtID, nmUUID, subjectName, documents, даты…) обратно не шлём.
UPDATE_FIELDS = ('nmID', 'vendorCode', 'brand', 'title', 'description',
                 'dimensions', 'characteristics', 'sizes')
DIMENSION_FIELDS = ('length', 'width', 'height', 'weightBrutto')


# Защитные стёкла — не плёнка, код 3919900000 им не подходит. Им нужен 7007…,
# а его WB разрешает только в предмете 9226 «Стекла защитные для авто»; пока
# стёкла лежат в 6466, ТН ВЭД им не ставим.
GLASS_CATEGORY_NAMES = (
    'Защитное стекло экранов мультимедиа, приборных панелей, климат-контроля',
)


def glass_category_ids():
    from catalog.models import Category
    ids = set()
    # имена из 1С бывают с хвостовыми пробелами — сравниваем после strip()
    for category in Category.objects.filter(name__icontains='стекл'):
        if category.name.strip() not in GLASS_CATEGORY_NAMES:
            continue
        ids.update(category.get_descendants(include_self=True).values_list('id', flat=True))
    return ids


def is_glass(product):
    if not product.category_id:
        return False
    names = {c.name.strip() for c in product.category.get_family()}
    return any(name in names for name in GLASS_CATEGORY_NAMES)


def tnved_characteristic():
    return {"id": TNVED_CHARC_ID, "value": [TNVED_CODE]}


def has_tnved(card):
    return any(
        ch.get('id') == TNVED_CHARC_ID and ch.get('value') == [TNVED_CODE]
        for ch in card.get('characteristics') or []
    )


def card_with_tnved(card):
    """Тело для v2/cards/update: карточка как есть плюс ТН ВЭД.

    update перезаписывает карточку целиком, поэтому все характеристики
    переносим с WB без изменений, а не собираем из базы.
    """
    payload = {key: card[key] for key in UPDATE_FIELDS if key in card}
    if 'dimensions' in payload:
        payload['dimensions'] = {
            key: payload['dimensions'][key]
            for key in DIMENSION_FIELDS if key in payload['dimensions']
        }
    payload['characteristics'] = [
        {"id": ch['id'], "value": ch['value']}
        for ch in card.get('characteristics') or []
        if ch.get('id') != TNVED_CHARC_ID
    ] + [tnved_characteristic()]
    return payload


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
        return {i.attribute_name.slug_name: i.value_attribute for i in attribs}

    def characteristics(self):
        list_characteristics = [
            {"id": 17596, "value": [self.attribs.get('material', 'Полиуритан')]},
            {"id": 378533, "value": [self.attribs['equipment']]},
            {"id": 14177451, "value": ["Россия"]},
        ]
        if not is_glass(self.prod):
            list_characteristics.append(tnved_characteristic())

        return list_characteristics

    def dataItemCard(self):
        if self.attribs.get('material') and self.attribs.get('width') and self.attribs.get(
                'length') and self.attribs.get('equipment') and self.attribs.get('color'):
            list_characteristics = self.characteristics()
            weight = self.attribs.get('weight_netto') or self.attribs.get('weight_brutto') or 0.3
            weight_brutto = float(str(weight).strip().replace(',', '.'))
            data = {
                "subjectID": self.SUB_CAT_ID,
                "variants": [
                    {
                        "vendorCode": self.prod.article_1C,
                        "title": self.prod.name[:59],
                        "description": self.prod.description,
                        "brand": "LEKALAPPF",
                        "dimensions": {
                            "length": int(self.attribs['length']),
                            "width": int(self.attribs['width']),
                            "height": int(self.attribs['height']),
                            "weightBrutto": weight_brutto,
                        },
                        "characteristics": list_characteristics,
                    }
                ]
            }
            return data
        else:
            return False

    def dataForUpdateItemCard(self, data):
        if self.attribs.get('material') and self.attribs.get('width') and self.attribs.get(
                'length') and self.attribs.get('equipment') and self.attribs.get('color'):
            list_characteristics = self.characteristics()
            data.update({
                "nmID": self.prod.wb.wb_id,
                "vendorCode": self.prod.article_1C,
                "brand": "LEKALAPPF",
                "title": self.prod.name[:59],
                "description": self.prod.description,
                "characteristics": list_characteristics,
            })
            del data['createdAt']
            del data['updatedAt']
            return data
        else:
            return False
