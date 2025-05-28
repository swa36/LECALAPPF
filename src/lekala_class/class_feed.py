from pathlib import Path
from django.db.models import Q, Count
import xml.etree.ElementTree as xml
from datetime import datetime, timezone, timedelta
from django.conf import settings
from catalog.models import MarkUpItems, Product, Category


class CreatorFeed:
    def __init__(self, name_market):
        self.url_site = 'http://lpff.ru'
        self.name_market = name_market
        self.root, self.shop, self.offers, self.categories = None, None, None, None
        self.mark_up = self.set_mark_up()
        self.set_main_data()

    def set_main_data(self):
        self.root = xml.Element("yml_catalog") if self.name_market != 'avito' else xml.Element("Ads")
        self.shop = xml.SubElement(self.root, 'shop') if self.name_market != 'avito' else None
        self.set_data()
        self.categories = xml.SubElement(self.shop, 'categories') if self.name_market != 'avito' else None
        self.offers = xml.SubElement(self.shop, 'offers') if self.name_market != 'avito' else xml.Element('items')
        if self.name_market == 'avito':
            self.offers.attrib = {'date': datetime.now().isoformat(timespec='seconds'), 'formatVersion': '1'}

    def set_data(self):
        tz = timezone(timedelta(hours=3))
        # Текущее время с временной зоной
        dt = datetime.now(tz)
        # Форматируем ISO 8601 с таймзоной
        date_str = dt.isoformat(timespec="seconds")
        if self.name_market == 'avito':
            self.root.attrib = {'date': datetime.now().isoformat(timespec='seconds'), 'formatVersion': '1'}
        else:
            self.root.attrib = {'date': date_str}
        if self.name_market in ['yandex', 'vk']:
            xml.SubElement(self.shop, 'name').text = 'VDF-LIGHT'
            currencies = xml.SubElement(self.shop, 'currencies')
            xml.SubElement(currencies, 'currency').attrib = {'id': 'RUB', 'rate': '1'}
            xml.SubElement(self.shop, 'company').text = 'ИП Гришин Ю.Н.'
            xml.SubElement(self.shop, 'url').text = self.url_site
        if self.name_market == 'yandex':
            delivery_options = xml.SubElement(self.shop, 'delivery-options')
            options_delivery = xml.SubElement(delivery_options, 'option')
            options_delivery.attrib = {'cost': '1500', 'days': '50'}

    def set_mark_up(self):
        query_mark_up = MarkUpItems.objects.last()
        mark_up = {
            'ali': query_mark_up.aliexpress_mark_up,
            'avito': query_mark_up.avito_mark_up,
        }
        return mark_up.get(self.name_market, None)

    def create_items(self):
        products = Product.objects.annotate(image_count=Count('images')).filter(
            Q(image_count__gt=0) & Q(stock__gt=0) & Q(prices__retail_price__gt=0) & Q(ozon__isnull=False)
        )
        self.create_data_category()
        for c in products:
            if self.name_market == 'yandex':
                continue
            item_data = self._get_item_data(c)
            if self.name_market == 'avito':
                if item_data['quantity_items'] == 0:
                    continue
                offer = xml.SubElement(self.root, 'Ad')
            else:
                offer = xml.SubElement(self.offers, 'offer')
                offer.attrib = {
                    'id': str(c.id),
                }
            self.set_description(offer, item_data)
            if self.name_market == 'avito':
                images = xml.SubElement(offer, 'Images')
                self.set_img(c, images)
                self._feed_avito(offer, item_data)
            else:
                self.set_img(c, offer)
                categoryId = xml.SubElement(offer, 'categoryId')
                categoryId.text = str(
                    c.category.get_root().id if self.name_market == 'vk' else str(
                        c.category.id))
                if self.name_market in ['yandex', 'vk']:
                    self._feed_for_yandex_vk(offer, item_data)
                elif self.name_market == 'ali':
                    self._feed_ali(offer, item_data)

    def exlude_category(sefl):
        category_archive = Category.objects.get(name='Архив')
        list_family_archive = [c.id for c in category_archive.get_family()]
        category_tape = Category.objects.get(name='Плёнка для бронирования фар')
        list_family_tape = [c.id for c in category_tape.get_family()]
        category_frame = Category.objects.get(name='Переходные рамки')
        list_final = list_family_archive + list_family_tape
        list_final.append(category_frame.id)
        return list_final

    def create_data_category(self):
        categoryes = Category.objects.all()
        if self.name_market == 'vk':
            for cat in categoryes:
                if cat.is_root_node():
                    category = xml.SubElement(self.categories, 'category')
                    category.attrib = {'id': str(cat.id)}
                    category.text = cat.name
        elif self.name_market in ['yandex', 'ali']:
            for cat in categoryes:
                if cat.is_root_node():
                    category = xml.SubElement(self.categories, 'category')
                    category.attrib = {'id': str(cat.id)}
                    category.text = cat.name
                    if not cat.is_leaf_node():
                        for sub_cat in cat.get_children():
                            sub_category = xml.SubElement(self.categories, 'category')
                            sub_category.attrib = {'id': str(sub_cat.id),
                                                   'parentId': str(cat.id)}
                            sub_category.text = sub_cat.name
                            if not sub_cat.is_leaf_node():
                                for sub_sub_cat in sub_cat.get_children():
                                    sub_sub_category = xml.SubElement(self.categories, 'category')
                                    sub_sub_category.attrib = {'id': str(sub_sub_cat.id),
                                                               'parentId': str(sub_cat.id)
                                                               }
                                    sub_sub_category.text = sub_sub_cat.name
                                    if not sub_sub_cat.is_leaf_node():
                                        for sub_sub_sub_cat in sub_sub_cat.get_children():
                                            sub_sub_sub_category = xml.SubElement(self.categories, 'category')
                                            sub_sub_sub_category.attrib = {
                                                'id': str(sub_sub_sub_cat.id),
                                                'parentId': str(
                                                    sub_sub_cat.id)
                                            }
                                            sub_sub_sub_category.text = sub_sub_sub_cat.name

    def _feed_ali(self, offer, data_item):
        price = xml.SubElement(offer, 'price')
        price.text = str(data_item['price_items'] + (self.mark_up * data_item['price_items']) / 100)
        if data_item['producer_items']:
            brand = xml.SubElement(offer, 'brand')
            brand.text = data_item['producer_items']
        article = xml.SubElement(offer, 'article')
        article.text = data_item['article_items']
        if data_item['length'] and data_item['width'] and data_item['height']:
            length = xml.SubElement(offer, 'length')
            length.text = str(data_item['length'])
            width = xml.SubElement(offer, 'width')
            width.text = str(data_item['width'])
            height = xml.SubElement(offer, 'height')
            height.text = str(data_item['height'])
        if data_item['weight_items']:
            weight = xml.SubElement(offer, 'weight')
            weight.text = data_item['weight_items']
        quantity = xml.SubElement(offer, 'quantity')
        quantity.text = str(data_item['quantity_items'])

    def _feed_avito(self, offer, data_item):
        id = xml.SubElement(offer, 'Id')
        id.text = str(data_item['id'])
        address = xml.SubElement(offer, 'Address')
        address.text = 'Калужская обл., Калуга, ул. Механизаторов 40'
        category = xml.SubElement(offer, 'Category')
        category.text = 'Запчасти и аксессуары'
        title = xml.SubElement(offer, 'Title')
        title.text = data_item['name'][:50]
        GoodsType = xml.SubElement(offer, 'GoodsType')
        GoodsType.text = 'Аксессуары'
        AdType = xml.SubElement(offer, 'AdType')
        AdType.text = 'Товар от производителя'
        productType = xml.SubElement(offer, 'ProductType')
        productType.text = 'Защита и декор'
        accessoryType = xml.SubElement(offer, 'AccessoryType')
        accessoryType.text = 'Наклейки, шильдики и значки'
        price = xml.SubElement(offer, 'Price')
        price_item_frame = data_item['price_items'] + (
                self.mark_up * data_item['price_items']) / 100
        price.text = f'{round(price_item_frame * 2, -2) // 2}'
        delivery = xml.SubElement(offer, 'Delivery')
        delivery_pvz = xml.SubElement(delivery, 'Option')
        delivery_pvz.text = 'ПВЗ'
        delivery_courier = xml.SubElement(delivery, 'Option')
        delivery_courier.text = 'Курьер'
        delivery_postamat = xml.SubElement(delivery, 'Option')
        delivery_postamat.text = 'Постамат'
        condition = xml.SubElement(offer, 'Condition')
        condition.text = 'Новое'
        manager_name = xml.SubElement(offer, 'ManagerName')
        manager_name.text = 'LekalaPPF  Manager'
        contact_phone = xml.SubElement(offer, 'ContactPhone')
        contact_phone.text = '+7 900 572-92-29'
        brand = xml.SubElement(offer, 'Brand')
        brand.text = 'LekalaPPF'
        oem = xml.SubElement(offer, 'OEM')
        oem.text = str(data_item['article_items'])
        availability = xml.SubElement(offer, 'Availability')
        if data_item['quantity_items'] > 0:
            availability.text = 'В наличии'
        else:
            availability.text = 'Под заказ'
        listingfee = xml.SubElement(offer, 'ListingFee')
        listingfee.text = 'Package'
        internetcalls = xml.SubElement(offer, 'InternetCalls')
        internetcalls.text = 'Да'
        calls_devices = xml.SubElement(offer, 'CallsDevices')
        calls_devices.text = '5081402173'
        weightForDelivery = xml.SubElement(offer, 'WeightForDelivery')
        weightForDelivery.text = data_item['weight_items']
        lengthForDelivery = xml.SubElement(offer, 'WeightForDelivery')
        lengthForDelivery.text = data_item['length']
        heightForDelivery = xml.SubElement(offer, 'HeightForDelivery')
        heightForDelivery.text = data_item['height']
        widthForDelivery = xml.SubElement(offer, 'WidthForDelivery')
        widthForDelivery.text = data_item['width']
        item = xml.SubElement(self.offers, 'item')
        id = xml.SubElement(item, 'id')
        id.text = str(data_item['id'])
        remains = xml.SubElement(item, 'stock')
        remains.text = str(data_item['quantity_items'])

    def _feed_for_yandex_vk(self, offer, data_item):
        offer.attrib['available'] = 'true' if data_item['quantity_items'] > 0 else 'false'
        url = xml.SubElement(offer, 'url')
        url.text = data_item['url']
        currencyId = xml.SubElement(offer, 'currencyId')
        currencyId.text = 'RUB'
        xml.SubElement(offer, 'store').text = 'true'
        xml.SubElement(offer, 'pickup').text = 'true'
        xml.SubElement(offer, 'delivery').text = 'true'
        xml.SubElement(offer, 'name').text = data_item['name']
        xml.SubElement(offer, 'vendorCode').text = data_item['article_items']
        xml.SubElement(offer, 'description').text = data_item['name']
        xml.SubElement(offer, 'sales_notes').text = 'Оплата: Наличные, Б/Н, пластиковые карты'
        price = xml.SubElement(offer, 'price')
        price.text = str(data_item['price_items'])
        if data_item['price_discount'] > 0:
            price.text = str(data_item['price_discount'])
            oldprice = xml.SubElement(offer, 'oldprice')
            oldprice.text = str(data_item['price_discount'])
        if data_item['producer_items']:
            pr = xml.SubElement(offer, 'vendor')
            pr.text = data_item['producer_items'].name_producer if data_item['producer_items'] else 'VDF'
        if data_item['sizes_items']:
            lenght, width, height = data_item['sizes_items'].split('X')
            if float(lenght) == 0:
                lenght = '1'
            if float(width) == 0:
                width = '1'
            if float(height) == 0:
                height = '1'
            xml.SubElement(offer, 'dimensions').text = f'{lenght}/{width}/{height}'
        if data_item['weight_items']:
            weight = xml.SubElement(offer, 'weight')
            if float(data_item['weight_items']) < 0.1:
                data_item['weight_items'] = '0.1'
            weight.text = data_item['weight_items']
            # if self.name_market != 'vk':
            #     weight.attrib = {'name': 'Weight', 'unit': 'кг'}
        if data_item['stroke_code'] and data_item['stroke_code'].startswith('2'):
            strokeCode = xml.SubElement(offer, 'barcode')
            strokeCode.text = data_item['stroke_code']
        if self.name_market != 'yandex':
            if 'color_temperature' in data_item and data_item['color_temperature']:
                ct = xml.SubElement(offer, 'param')
                ct.attrib = {'name': 'Цветовая темература'}
                ct.text = data_item['color_temperature']
            if 'work_voltage' in data_item and data_item['work_voltage']:
                wv = xml.SubElement(offer, 'param')
                wv.attrib = {'name': 'Рабочее напряжение'}
                wv.text = data_item['work_voltage']

    def set_img(self, item, offer) -> None:
        all_img = item.images.all().order_by('-main')

        limit_by_market = {
            'yandex': 20,
            'ali': 5,
            'avito': 9,
        }
        max_images = limit_by_market.get(self.name_market)
        if max_images:
            all_img = all_img[:max_images]
        for img in all_img:
            
            base_url = img.image.url
            url = self.url_site + base_url
            tag_name = 'Image' if self.name_market == 'avito' else 'picture'
            elem = xml.SubElement(offer, tag_name)
            if tag_name == 'Image':
                elem.attrib = {'url': url}
            else:
                elem.text = url

    def set_description(self, offer, data_item):
        if self.name_market != 'yandex':
            desc = data_item['desc']
            # for i in soup:
            #     if self.name_market == 'avito':
            #         for i in soup.findAll('iframe'):
            #             VideoURL = xml.SubElement(offer, 'VideoURL')
            #             VideoURL.text = i['src']
            #             i.unwrap()
            #             continue
            #     if i.find('br'):
            #         list_new_string = [z for z in i.stripped_strings]
            #         for s in list_new_string:
            #             desc += s + '<br/>'
            #     else:
            #         desc += i.text + '<br/>'
            #     if 'внимание' in i.text.lower():
            #         str_stop = 'требует проверки совместимость'.split(' ')
            #         if not any(word in i.text.lower() for word in str_stop):
            #             break
            description = xml.SubElement(offer, 'description' if self.name_market != 'avito' else 'Description')
            if self.name_market == 'vk':
                desc = desc[:4000]
            elif self.name_market == 'ali':
                desc = f'<![CDATA[{desc}]]>'
            description.text = desc

    def _get_item_data(self, c):
        attributes = {i.attribute_name.slug_name:i.value_attribute for i in c.additional_attributes.all()}
        data = {}
        data['id'] = c.code_1C
        data['id_item'] = c.id
        data['name'] = c.name
        data['desc'] = c.description
        data['article_items'] = c.article_1C
        data['price_items'] = c.prices.retail_price
        data['price_discount'] = c.prices.retail_price
        data['producer_items'] = "LekalaPPF"
        data['length'] = attributes['length']
        data['width'] = attributes['width']
        data['height'] = attributes['height']
        data['weight_items'] = attributes.get('weight_netto') if attributes.get('weight_netto') else attributes.get('weight_brutto')
        data['quantity_items'] = c.stock
        # data['url'] = self.url_site + c.get_absolute_url()
        # data['stroke_code'] = c.stroke_code if hasattr(c, 'stroke_code') else c.frame_in_article.stroke_code
        return data


    def save(self):
        filename = self.name_market + '.xml'
        path_file = Path(settings.BASE_DIR) / Path('feed_for_marketplace')
        tree = xml.ElementTree(self.root)
        if self.name_market == 'avito':
            avito_stock = 'avito_stock.xml'
            stock = xml.ElementTree(self.offers)
            tree.write(path_file / filename, xml_declaration=True, encoding='UTF-8')
            stock.write(path_file / avito_stock, xml_declaration=True, encoding='UTF-8')
        else:
            tree.write(Path(path_file / filename), xml_declaration=True, encoding='UTF-8')