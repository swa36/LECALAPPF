import os
from datetime import datetime
from itertools import product
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from src.lekala_class.class_1C.ExChange1C import ExChange1C
from catalog.models import *


class GetData1C(ExChange1C):
    def __init__(self):
        super().__init__()

    def set_name_attribute(self):
        data_name_attrib = self.get_name_additional_attributes()['value']
        for i in data_name_attrib:
            NameAdditionalAttributes.objects.update_or_create(
                uuid_1C=i['Ref_Key'], defaults={'name_attribute': i['Description']}
            )
        return


    def set_type_price(self):
        suffix_type_price = {
            'Закупочная': 'cost_price',
            'Оптовая': 'wholesale_price',
            'Опт2': 'wholesale_price_2',
            'Опт3': 'wholesale_price_3',
            'Розничная': 'retail_price'
        }
        data_type_price = self.get_type_price()['value']
        for i in data_type_price:
            TypePrices.objects.update_or_create(
                uuid_1C=i['Ref_Key'],
                defaults={
                    'type_price': i['Description'],
                    'suffix': suffix_type_price[i['Description']],
                }
            )
        return

    def save_image_errors_to_excel(self, data_list, file_path='ошибки_изображений.xlsx'):
        if os.path.exists(file_path):
            wb = load_workbook(file_path)
            ws = wb.active
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = 'Ошибки загрузки'
            headers = ['Наименование товара', 'Артикул в 1С']
            ws.append(headers)

        for row in data_list:
            # обрезаем до 2 столбцов на случай, если пришлют 3
            ws.append(row[:2])

        # Автоширина по двум колонкам
        for col in ws.iter_cols(min_row=1, max_row=ws.max_row, max_col=2):
            max_length = 0
            column_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            ws.column_dimensions[column_letter].width = max_length + 2

        wb.save(file_path)

    # Основной метод
    def download_img_from_1C(self, item_uuid, uuid_main_img=None):
        product = Product.objects.get(uuid_1C=item_uuid)
        response = self.get_all_img(item_uuid)
        all_img = response.get('value', [])
        if not all_img:
            print(f"⚠️ Нет изображений для: {product.name} ({product.article_1C})")
            return  # нет изображений — ничего не делать
        for i in all_img:
            img_data = self.get_img_base64(i['Ref_Key'])
            if 'odata.error' in img_data:
                print(f"❌ Ошибка загрузки: {product.name} {product.article_1C} {product.stock}")
                # записываем один раз об ошибке на продукт и прекращаем цикл
                self.save_image_errors_to_excel([
                    [product.name, product.article_1C]
                ])
                return  # прерываем дальнейшую обработку этого продукта

        # если всё прошло успешно — дальше можно обработать сохранение изображений
        print(f"✅ Успешно загружены изображения для: {product.name} ({product.article_1C})")

    def set_catalog_data_stock(self, data_catalog, data_stock, data_price):
        for item in data_catalog:
            stock = 0
            item_stock = list(filter(lambda data_stock: data_stock['Номенклатура_Key'] == item['Ref_Key'], data_stock))
            for q in item_stock:
                if q['RecordType'] == 'Receipt':
                    stock += q['ВНаличии']
                elif q['RecordType'] == 'Expense':
                    stock -= q['ВНаличии']
            stock = 0 if stock < 0 else stock
            product, created = Product.objects.update_or_create(
                uuid_1C=item['Ref_Key'],
                defaults={
                    'article_1C': item['Артикул'].strip(),
                    'code_1C': item['Code'],
                    'data_version': item['DataVersion'],
                    'name': item['Description'].strip(),
                    'description': item['Описание'],
                    'stock': stock
                }
            )
            price_item = list(filter(lambda data_price: data_price['Номенклатура_Key'] == item['Ref_Key'],
                                     data_price))
            price_dict = {}
            for tp in TypePrices.objects.all():
                value_price = list(filter(lambda price_item: price_item['ВидЦены_Key'] == str(tp.uuid_1C),
                                          price_item))
                latest_price = 0
                if value_price:
                    latest_price = max(
                        value_price,
                        key=lambda p: datetime.fromisoformat(p['Period'].split('T')[0])
                    )['Цена']
                price_dict[tp.suffix] = latest_price
            Prices.objects.update_or_create(
                product=product,
                defaults={**price_dict}
            )
            if created or product.data_version != item['DataVersion']:
                # Обновление доп. атрибутов
                additional_attributes = item['ДополнительныеРеквизиты']
                for attribute in additional_attributes:
                    ValueAdditionalAttributes.objects.update_or_create(
                        product=product,
                        attribute_name=NameAdditionalAttributes.objects.get(uuid_1C=attribute['Свойство_Key']),
                        defaults={
                            'value_attribute': attribute['Значение']
                        }
                    )

                # ✅ Обновление изображений
                id_main_img = item.get('ФайлКартинки_Key')
                if id_main_img:
                    self.get_img(product.id, id_main_img)

        return
