from unittest import mock

from django.test import SimpleTestCase, TestCase

import src.lekala_class.class_marketplace.WBItem as WBItem_module

from src.lekala_class.class_marketplace.WBItem import (
    TNVED_CHARC_ID,
    GLASS_CATEGORY_NAMES,
    TNVED_CODE,
    GLASS_SUBJECT_ID,
    GLASS_TNVED_CODE,
    FILM_SUBJECT_ID,
    MATERIAL_CHARC_ID,
    WBItem,
    card_is_done,
    card_with_tnved,
    target_tnved,
    documents_not_required,
    glass_category_ids,
    has_tnved,
    is_glass,
)


def wb_card(**overrides):
    """Карточка в том виде, в каком её отдаёт v2/get/cards/list."""
    card = {
        "nmID": 2084204497,
        "imtID": 4412790054,
        "nmUUID": "01a1976c-04a4-7384-a923-718d778f1f4f",
        "subjectID": 6466,
        "subjectName": "Пленки защитные для авто",
        "vendorCode": "P508II18SLS",
        "brand": "LEKALAPPF",
        "title": "Плёнка для стоек",
        "description": "Описание",
        "needKiz": False,
        "dimensions": {"width": 5, "height": 5, "length": 30, "weightBrutto": 0.3, "isValid": True},
        "characteristics": [
            {"id": 378533, "name": "Комплектация", "value": ["Плёнка"]},
            {"id": 90675, "name": "Длина предмета", "value": 30},
        ],
        "sizes": [{"chrtID": 3666104050, "techSize": "0", "wbSize": "", "skus": ["2060430757699"]}],
        "createdAt": "2026-11-01T14:03:24Z",
        "updatedAt": "2026-11-01T14:03:25Z",
    }
    card.update(overrides)
    return card


class CardWithTnvedTest(SimpleTestCase):
    def test_adds_tnved_and_keeps_other_characteristics(self):
        payload = card_with_tnved(wb_card())

        self.assertEqual(
            payload["characteristics"],
            [
                {"id": 378533, "value": ["Плёнка"]},
                {"id": 90675, "value": 30},
                {"id": TNVED_CHARC_ID, "value": [TNVED_CODE]},
            ],
        )

    def test_keeps_only_fields_accepted_by_update(self):
        payload = card_with_tnved(wb_card())

        self.assertEqual(
            set(payload),
            {"nmID", "vendorCode", "brand", "title", "description",
             "dimensions", "characteristics", "sizes", "documents"},
        )
        self.assertEqual(payload["documents"], {"excludeDocuments": True})
        self.assertEqual(
            payload["dimensions"],
            {"width": 5, "height": 5, "length": 30, "weightBrutto": 0.3},
        )
        self.assertEqual(payload["sizes"][0]["chrtID"], 3666104050)

    def test_replaces_wrong_tnved_instead_of_duplicating(self):
        card = wb_card(characteristics=[
            {"id": TNVED_CHARC_ID, "name": "ТНВЭД", "value": ["3909509008"]},
        ])

        payload = card_with_tnved(card)

        self.assertEqual(
            payload["characteristics"],
            [{"id": TNVED_CHARC_ID, "value": [TNVED_CODE]}],
        )

    def test_without_code_keeps_characteristics_and_sets_flag(self):
        card = wb_card(characteristics=[
            {"id": TNVED_CHARC_ID, "name": "ТНВЭД", "value": ["1234567890"]},
            {"id": 378533, "name": "Комплектация", "value": ["Стекло"]},
        ])

        payload = card_with_tnved(card, code=None)

        self.assertEqual(payload["characteristics"], [
            {"id": TNVED_CHARC_ID, "value": ["1234567890"]},
            {"id": 378533, "value": ["Стекло"]},
        ])
        self.assertEqual(payload["documents"], {"excludeDocuments": True})

    def test_target_tnved(self):
        self.assertEqual(target_tnved(wb_card(), is_glass_card=False), TNVED_CODE)
        self.assertEqual(
            target_tnved(wb_card(subjectID=GLASS_SUBJECT_ID), is_glass_card=True),
            GLASS_TNVED_CODE,
        )

    def test_glass_in_film_subject_gets_film_code_while_9226_disabled(self):
        self.assertEqual(target_tnved(wb_card(subjectID=FILM_SUBJECT_ID), is_glass_card=True), TNVED_CODE)

    def test_glass_in_film_subject_waits_when_9226_enabled(self):
        with mock.patch.object(WBItem_module, 'GLASS_SUBJECT_ENABLED', True):
            self.assertIsNone(target_tnved(wb_card(subjectID=FILM_SUBJECT_ID), is_glass_card=True))

    def test_card_is_done(self):
        flag = {"excludeDocuments": True}
        with_code = [{"id": TNVED_CHARC_ID, "value": [TNVED_CODE]}]
        self.assertFalse(card_is_done(wb_card(characteristics=with_code), TNVED_CODE))
        self.assertFalse(card_is_done(wb_card(documents=flag), TNVED_CODE))
        self.assertTrue(card_is_done(wb_card(documents=flag, characteristics=with_code), TNVED_CODE))
        self.assertTrue(card_is_done(wb_card(documents=flag), None))

    def test_documents_not_required(self):
        self.assertFalse(documents_not_required(wb_card()))
        self.assertFalse(documents_not_required(wb_card(documents={"excludeDocuments": False})))
        self.assertTrue(documents_not_required(wb_card(documents={"excludeDocuments": True})))

    def test_has_tnved(self):
        self.assertFalse(has_tnved(wb_card()))
        self.assertFalse(has_tnved(wb_card(characteristics=[
            {"id": TNVED_CHARC_ID, "value": ["3909509008"]},
        ])))
        self.assertTrue(has_tnved(wb_card(characteristics=[
            {"id": TNVED_CHARC_ID, "value": [TNVED_CODE]},
        ])))


class GlassTest(TestCase):
    def setUp(self):
        import uuid
        from catalog.models import Category, Product
        root = Category.objects.create(uuid_1C=uuid.uuid4(), name=GLASS_CATEGORY_NAMES[0] + ' ')
        child = Category.objects.create(uuid_1C=uuid.uuid4(), name='Toyota', parent=root)
        film = Category.objects.create(uuid_1C=uuid.uuid4(), name='Лекала для салона автомобиля')
        self.glass_category = child
        self.glass = Product.objects.create(uuid_1C=uuid.uuid4(), article_1C='G1', code_1C='G1', name='Защитное стекло', category=child)
        self.film = Product.objects.create(uuid_1C=uuid.uuid4(), article_1C='F1', code_1C='F1',
                                           name='Плёнка для стоек лобового стекла', category=film)

    def test_is_glass_by_category_not_by_name(self):
        self.assertTrue(is_glass(self.glass))
        self.assertFalse(is_glass(self.film))

    def test_glass_category_ids_include_descendants(self):
        self.assertIn(self.glass_category.id, glass_category_ids())
        self.assertNotIn(self.film.category_id, glass_category_ids())

    def _wb_item(self, product):
        item = WBItem.__new__(WBItem)
        item.prod = product
        item.attribs = {'equipment': 'Комплект', 'material': 'Полиуретан'}
        return item

    def test_glass_stays_in_film_subject_while_9226_disabled(self):
        item = self._wb_item(self.glass)
        self.assertEqual(item.subject_id(), FILM_SUBJECT_ID)
        self.assertIn({"id": TNVED_CHARC_ID, "value": [TNVED_CODE]}, item.characteristics())

    @mock.patch.object(WBItem_module, 'GLASS_SUBJECT_ENABLED', True)
    def test_glass_goes_to_glass_subject_with_glass_code(self):
        item = self._wb_item(self.glass)
        self.assertEqual(item.subject_id(), GLASS_SUBJECT_ID)
        chars = item.characteristics()
        self.assertIn({"id": TNVED_CHARC_ID, "value": [GLASS_TNVED_CODE]}, chars)
        self.assertNotIn(MATERIAL_CHARC_ID, [c["id"] for c in chars])

    def test_film_keeps_film_subject_and_code(self):
        item = self._wb_item(self.film)
        self.assertEqual(item.subject_id(), FILM_SUBJECT_ID)
        self.assertIn({"id": TNVED_CHARC_ID, "value": [TNVED_CODE]}, item.characteristics())
