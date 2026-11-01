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


FILM_SUBJECT_ID = 6466

# Защитные стёкла — не плёнка, код 3919900000 им не подходит. Им нужен 7007…,
# а его WB разрешает только в предмете 9226 «Стекла защитные для авто».
# Сменить предмет через v2/cards/update нельзя (subjectID игнорируется), так что
# старые стёкла из 6466 переносятся в личном кабинете, новые заводятся сразу в 9226.
GLASS_SUBJECT_ID = 9226
GLASS_TNVED_CODE = '7007198008'
# Бренд LEKALAPPF в предмете 9226 не зарегистрирован — WB отклоняет карточки
# с ошибкой «Бренд не найден». Пока бренд не одобрят, стёкла живут в 6466 с
# плёночным кодом. После одобрения — True: новые стёкла пойдут в 9226.
GLASS_SUBJECT_ENABLED = False
# «Материал изделия» есть только у 6466
MATERIAL_CHARC_ID = 17596
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


# Подтверждение продавца, что разрешительные документы не нужны (галочка
# «Документы не требуются» в кабинете). Без него WB по 289-ФЗ блокирует новые и
# изменённые карточки с причиной documents_missing. Продукция своя, документы не
# требуются — решение владельца от 2026-11-01.
DOCUMENTS_NOT_REQUIRED = {"excludeDocuments": True}


def documents_not_required(card):
    return bool((card.get('documents') or {}).get('excludeDocuments'))


def tnved_characteristic(code=TNVED_CODE):
    return {"id": TNVED_CHARC_ID, "value": [code]}


def has_tnved(card, code=TNVED_CODE):
    return any(
        ch.get('id') == TNVED_CHARC_ID and ch.get('value') == [code]
        for ch in card.get('characteristics') or []
    )


def card_with_tnved(card, code=TNVED_CODE):
    """Тело для v2/cards/update: карточка как есть плюс ТН ВЭД и отметка
    «документы не требуются».

    update перезаписывает карточку целиком, поэтому все характеристики
    переносим с WB без изменений, а не собираем из базы. code=None — ТН ВЭД
    не трогаем (стёкла в 6466: стекольный код этот предмет не принимает).
    """
    payload = {key: card[key] for key in UPDATE_FIELDS if key in card}
    if 'dimensions' in payload:
        payload['dimensions'] = {
            key: payload['dimensions'][key]
            for key in DIMENSION_FIELDS if key in payload['dimensions']
        }
    characteristics = [
        {"id": ch['id'], "value": ch['value']}
        for ch in card.get('characteristics') or []
        if code is None or ch.get('id') != TNVED_CHARC_ID
    ]
    if code is not None:
        characteristics.append(tnved_characteristic(code))
    payload['characteristics'] = characteristics
    payload['documents'] = dict(DOCUMENTS_NOT_REQUIRED)
    return payload


def target_tnved(card, is_glass_card):
    """Какой ТН ВЭД должен стоять на карточке; None — не ставить."""
    if is_glass_card and card.get('subjectID') == GLASS_SUBJECT_ID:
        return GLASS_TNVED_CODE
    if is_glass_card and GLASS_SUBJECT_ENABLED:
        # стекло ждёт переноса в 9226 — плёночный код не ставим
        return None
    return TNVED_CODE


def card_is_done(card, code):
    if not documents_not_required(card):
        return False
    return code is None or has_tnved(card, code)


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

    def _glass_subject(self):
        return GLASS_SUBJECT_ENABLED and is_glass(self.prod)

    def subject_id(self):
        return GLASS_SUBJECT_ID if self._glass_subject() else FILM_SUBJECT_ID

    def characteristics(self):
        if self._glass_subject():
            return [
                {"id": 378533, "value": [self.attribs['equipment']]},
                {"id": 14177451, "value": ["Россия"]},
                tnved_characteristic(GLASS_TNVED_CODE),
            ]
        return [
            {"id": MATERIAL_CHARC_ID, "value": [self.attribs.get('material', 'Полиуритан')]},
            {"id": 378533, "value": [self.attribs['equipment']]},
            {"id": 14177451, "value": ["Россия"]},
            tnved_characteristic(),
        ]

    def dataItemCard(self):
        if self.attribs.get('material') and self.attribs.get('width') and self.attribs.get(
                'length') and self.attribs.get('equipment') and self.attribs.get('color'):
            list_characteristics = self.characteristics()
            weight = self.attribs.get('weight_netto') or self.attribs.get('weight_brutto') or 0.3
            weight_brutto = float(str(weight).strip().replace(',', '.'))
            data = {
                "subjectID": self.subject_id(),
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
                        "documents": dict(DOCUMENTS_NOT_REQUIRED),
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
