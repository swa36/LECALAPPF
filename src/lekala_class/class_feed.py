from pathlib import Path
from django.db.models import Q, Count
from datetime import datetime, timezone, timedelta
from django.conf import settings
from catalog.models import MarkUpItems, Product, Category
from lxml import etree as ET


class CreatorFeed:
    def __init__(self, name_market):
        self.url_site = 'http://lpff.ru'
        self.name_market = name_market
        self.root, self.shop, self.offers, self.categories = None, None, None, None
        self.mark_up = self.set_mark_up()
        self.set_main_data()

    def set_main_data(self):
        self.root = ET.Element("yml_catalog") if self.name_market != 'avito' else ET.Element("Ads")
        if self.name_market != 'avito':
            self.shop = ET.SubElement(self.root, 'shop')
            self.categories = ET.SubElement(self.shop, 'categories')
            self.offers = ET.SubElement(self.shop, 'offers')
        else:
            self.offers = ET.Element('items')
            self.offers.attrib.update({
                'date': datetime.now().isoformat(timespec='seconds'),
                'formatVersion': '1'
            })
        self.set_data()

    def set_data(self):
        tz = timezone(timedelta(hours=3))
        date_str = datetime.now(tz).isoformat(timespec="seconds")
        if self.name_market == 'avito':
            self.root.attrib.update({'date': date_str, 'formatVersion': '1'})
        else:
            self.root.set('date', date_str)

        if self.name_market in ['yandex', 'vk']:
            ET.SubElement(self.shop, 'name').text = 'VDF-LIGHT'
            currencies = ET.SubElement(self.shop, 'currencies')
            ET.SubElement(currencies, 'currency', id='RUB', rate='1')
            ET.SubElement(self.shop, 'company').text = 'ИП Гришин Ю.Н.'
            ET.SubElement(self.shop, 'url').text = self.url_site

        if self.name_market == 'yandex':
            delivery_options = ET.SubElement(self.shop, 'delivery-options')
            ET.SubElement(delivery_options, 'option', cost='1500', days='50')

    def set_mark_up(self):
        query_mark_up = MarkUpItems.objects.last()
        return {
            'ali': query_mark_up.aliexpress_mark_up,
            'avito': query_mark_up.avito_mark_up
        }.get(self.name_market)

    def create_items(self):
        products = Product.objects.annotate(image_count=Count('images')).filter(
            Q(image_count__gt=0) & Q(stock__gt=0) & Q(prices__retail_price__gt=0) & Q(ozon__isnull=False)
        )
        self.create_data_category()
        for c in products:
            if self.name_market == 'yandex':
                continue
            item_data = self._get_item_data(c)
            if self.name_market == 'avito' and item_data['quantity_items'] == 0:
                continue
            if self.name_market == 'avito':
                offer = ET.SubElement(self.root, 'Ad')
            else:
                offer = ET.SubElement(self.offers, 'offer')
                if self.name_market == 'ali':
                    offer.set('id', str(c.code_1C))
                else:
                    offer.set('id', str(c.id))

            self.set_description(offer, item_data)

            if self.name_market == 'avito':
                images = ET.SubElement(offer, 'Images')
                self.set_img(c, images)
                self._feed_avito(offer, item_data)
            else:
                self.set_img(c, offer)
                ET.SubElement(offer, 'categoryId').text = str(
                    c.category.get_root().id if self.name_market == 'vk' else c.category.id
                )
                if self.name_market in ['yandex', 'vk']:
                    self._feed_for_yandex_vk(offer, item_data)
                elif self.name_market == 'ali':
                    self._feed_ali(offer, item_data)

    def exlude_category(self):
        archive = Category.objects.get(name='Архив').get_family()
        tape = Category.objects.get(name='Плёнка для бронирования фар').get_family()
        frame = Category.objects.get(name='Переходные рамки')
        return [c.id for c in archive] + [c.id for c in tape] + [frame.id]

    def create_data_category(self):
        categories = Category.objects.all()
        if self.name_market in ['vk', 'yandex', 'ali']:
            for cat in categories:
                if cat.is_root_node():
                    elem = ET.SubElement(self.categories, 'category', id=str(cat.id))
                    elem.text = cat.name
                    for sub in cat.get_children():
                        sub_elem = ET.SubElement(self.categories, 'category', id=str(sub.id), parentId=str(cat.id))
                        sub_elem.text = sub.name
                        for sub2 in sub.get_children():
                            sub2_elem = ET.SubElement(self.categories, 'category', id=str(sub2.id), parentId=str(sub.id))
                            sub2_elem.text = sub2.name
                            for sub3 in sub2.get_children():
                                sub3_elem = ET.SubElement(self.categories, 'category', id=str(sub3.id), parentId=str(sub2.id))
                                sub3_elem.text = sub3.name

    def _feed_ali(self, offer, data):
        ET.SubElement(offer, 'price').text = str(data['price_items'] + (self.mark_up * data['price_items']) / 100)
        ET.SubElement(offer, 'brand').text = data['producer_items']
        ET.SubElement(offer, 'article').text = data['id']
        ET.SubElement(offer, 'name').text = data['name']
        for tag in ['length', 'width', 'height']:
            if data[tag]:
                ET.SubElement(offer, tag).text = str(data[tag])
        if data['weight_items']:
            ET.SubElement(offer, 'weight').text = data['weight_items']
        ET.SubElement(offer, 'quantity').text = str(data['quantity_items'])

    def _feed_avito(self, offer, data):
        values = {
            'Id': data['id'],
            'Address': 'Калужская обл., Калуга, ул. Механизаторов 40',
            'Category': 'Запчасти и аксессуары',
            'Title': data['name'][:50],
            'GoodsType': 'Аксессуары',
            'AdType': 'Товар от производителя',
            'ProductType': 'Защита и декор',
            'AccessoryType': 'Наклейки, шильдики и значки',
            'Price': str(round((data['price_items'] + (self.mark_up * data['price_items']) / 100) * 2, -2) // 2),
            'Condition': 'Новое',
            'ManagerName': 'LekalaPPF Manager',
            'ContactPhone': '+7 900 572-92-29',
            'Brand': 'LekalaPPF',
            'OEM': data['article_items'],
            'Availability': 'В наличии' if data['quantity_items'] > 0 else 'Под заказ',
            'ListingFee': 'Package',
            'InternetCalls': 'Да',
            'CallsDevices': '5081402173',
            'WeightForDelivery': data['weight_items'],
            'LengthForDelivery': data['length'],
            'HeightForDelivery': data['height'],
            'WidthForDelivery': data['width']
        }
        for tag, val in values.items():
            ET.SubElement(offer, tag).text = val
        delivery = ET.SubElement(offer, 'Delivery')
        for method in ['ПВЗ', 'Курьер', 'Постамат']:
            ET.SubElement(delivery, 'Option').text = method

    def _feed_for_yandex_vk(self, offer, data):
        offer.set('available', 'true' if data['quantity_items'] > 0 else 'false')
        ET.SubElement(offer, 'url').text = data['url']
        ET.SubElement(offer, 'currencyId').text = 'RUB'
        for tag in ['store', 'pickup', 'delivery']:
            ET.SubElement(offer, tag).text = 'true'
        ET.SubElement(offer, 'name').text = data['name']
        ET.SubElement(offer, 'vendorCode').text = data['article_items']
        ET.SubElement(offer, 'description').text = data['name']
        ET.SubElement(offer, 'sales_notes').text = 'Оплата: Наличные, Б/Н, пластиковые карты'
        ET.SubElement(offer, 'price').text = str(data['price_discount'])
        if data['price_discount'] > 0:
            ET.SubElement(offer, 'oldprice').text = str(data['price_items'])
        if data['producer_items']:
            ET.SubElement(offer, 'vendor').text = data['producer_items']
        if data.get('sizes_items'):
            l, w, h = data['sizes_items'].split('X')
            ET.SubElement(offer, 'dimensions').text = f'{l or 1}/{w or 1}/{h or 1}'
        if data['weight_items']:
            ET.SubElement(offer, 'weight').text = data['weight_items']
        if data.get('stroke_code') and data['stroke_code'].startswith('2'):
            ET.SubElement(offer, 'barcode').text = data['stroke_code']

    def set_img(self, item, offer):
        all_img = item.images.all().order_by('-main')
        limit_by_market = {'yandex': 20, 'ali': 5, 'avito': 9}
        all_img = all_img[:limit_by_market.get(self.name_market, 0)]
        for img in all_img:
            url = self.url_site + img.image.url
            tag = 'Image' if self.name_market == 'avito' else 'picture'
            elem = ET.SubElement(offer, tag)
            if tag == 'Image':
                elem.set('url', url)
            else:
                elem.text = url

    def set_description(self, offer, data):
        desc = data['desc']
        tag = 'description' if self.name_market != 'avito' else 'Description'
        element = ET.SubElement(offer, tag)
        if self.name_market == 'vk':
            element.text = desc[:4000]
        elif self.name_market == 'ali':
            element.text = ET.CDATA(desc)
        else:
            element.text = desc

    def _get_item_data(self, c):
        attrs = {a.attribute_name.slug_name: a.value_attribute for a in c.additional_attributes.all()}
        return {
            'id': c.code_1C,
            'id_item': c.id,
            'name': c.name,
            'desc': c.description,
            'article_items': c.article_1C,
            'price_items': c.prices.retail_price,
            'price_discount': c.prices.retail_price,
            'producer_items': "LekalaPPF",
            'length': attrs.get('length', ''),
            'width': attrs.get('width', ''),
            'height': attrs.get('height', ''),
            'weight_items': attrs.get('weight_netto') or attrs.get('weight_brutto', ''),
            'quantity_items': c.stock,
            # 'url': self.url_site + c.get_absolute_url(),
            # 'stroke_code': getattr(c, 'stroke_code', ''),
            'sizes_items': attrs.get('sizes', '')
        }

    def save(self):
        filename = self.name_market + '.xml'
        path_file = Path(settings.BASE_DIR) / 'feed_for_marketplace'
        path_file.mkdir(parents=True, exist_ok=True)
        with open(path_file / filename, 'wb') as f:
            f.write(ET.tostring(self.root, pretty_print=True, xml_declaration=True, encoding='UTF-8'))
        if self.name_market == 'avito':
            with open(path_file / 'avito_stock.xml', 'wb') as f:
                f.write(ET.tostring(self.offers, pretty_print=True, xml_declaration=True, encoding='UTF-8'))
