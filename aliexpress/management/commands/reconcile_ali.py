from collections import defaultdict

from django.core.management.base import BaseCommand

from aliexpress.models import AliData
from catalog.models import Product
from src.lekala_class.class_marketplace.AliExpress import AliExpress


class Command(BaseCommand):
    help = 'Reconcile AliExpress product cards with the local catalog.'
    DELETE_BATCH_SIZE = 20
    LINK_BATCH_SIZE = 1000
    STOCK_BATCH_SIZE = 400

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true')

    def handle(self, *args, **options):
        client = AliExpress()
        plan = self._build_plan(client.get_all_products())
        self._write_plan(plan, execute=options['execute'])
        if options['execute']:
            self._apply_plan(client, plan)

    def _build_plan(self, cards):
        products = {
            product.code_1C: product
            for product in Product.objects.only('id', 'code_1C', 'stock')
        }
        linked_ids = set(
            AliData.objects.exclude(id_ali__isnull=True).values_list('id_ali', flat=True)
        )
        cards_by_code = defaultdict(list)
        plan = {
            'missing_sku_ids': [], 'missing_local_ids': [], 'duplicate_ids': [],
            'delete_ids': [], 'surviving_links': [], 'stock_updates': [],
            'offline_ids': [],
        }
        for card in cards:
            card_id = str(card.get('id', ''))
            code = self._first_sku_code(card)
            if not code:
                plan['missing_sku_ids'].append(card_id)
            elif code not in products:
                plan['missing_local_ids'].append(card_id)
            else:
                cards_by_code[code].append(card)
        plan['delete_ids'].extend(plan['missing_sku_ids'])
        plan['delete_ids'].extend(plan['missing_local_ids'])
        for code, matching_cards in cards_by_code.items():
            kept_card = self._card_to_keep(matching_cards, linked_ids)
            product = products[code]
            kept_id = str(kept_card['id'])
            plan['surviving_links'].append((product, kept_id))
            if product.stock > 0:
                plan['stock_updates'].append(self._stock_update(product, kept_id))
                if self._is_offline(kept_card):
                    plan['offline_ids'].append(kept_id)
            for card in matching_cards:
                card_id = str(card['id'])
                if card_id != kept_id:
                    plan['duplicate_ids'].append(card_id)
        plan['delete_ids'].extend(plan['duplicate_ids'])
        return plan

    @staticmethod
    def _first_sku_code(card):
        skus = card.get('sku') or []
        return skus[0].get('code') if skus else None

    @staticmethod
    def _card_to_keep(cards, linked_ids):
        linked_cards = [card for card in cards if int(card['id']) in linked_ids]
        return min(linked_cards or cards, key=lambda card: card.get('ali_created_at') or '')

    @staticmethod
    def _stock_update(product, remote_id):
        return {
            'product_id': remote_id,
            'skus': [{'sku_code': product.code_1C, 'inventory': str(product.stock)}],
        }

    @staticmethod
    def _is_offline(card):
        status = str(card.get('status', '')).lower()
        return status == 'offline' or card.get('is_online') is False or card.get('online') is False

    def _write_plan(self, plan, execute):
        mode = 'execution' if execute else 'dry-run'
        self.stdout.write(f'AliExpress reconciliation plan ({mode}):')
        self.stdout.write(f"missing SKU: {len(plan['missing_sku_ids'])}")
        self.stdout.write(f"missing local products: {len(plan['missing_local_ids'])}")
        self.stdout.write(f"duplicates: {len(plan['duplicate_ids'])}")
        self.stdout.write(f"planned deletions: {len(plan['delete_ids'])}")
        self.stdout.write(f"stock updates: {len(plan['stock_updates'])}")
        self.stdout.write(f"online restores: {len(plan['offline_ids'])}")
        if not execute:
            self.stdout.write('Dry-run complete: no remote or local changes made.')

    def _apply_plan(self, client, plan):
        deleted_cards = 0
        deleted_links = 0
        failed_delete_batches = 0
        failed_stock_batches = 0
        failed_online_batches = 0

        self.stdout.write('Starting execution. Press Ctrl+C to stop safely between requests.')
        delete_batches = list(self._batches(plan['delete_ids'], self.DELETE_BATCH_SIZE))
        for number, batch in enumerate(delete_batches, start=1):
            self.stdout.write(
                f'Delete batch {number}/{len(delete_batches)}: {len(batch)} cards'
            )
            if client.delete_products(batch) is True:
                deleted_cards += len(batch)
                deleted_links += AliData.objects.filter(id_ali__in=batch).delete()[0]
                self.stdout.write(f'Delete batch {number}/{len(delete_batches)} succeeded')
            else:
                failed_delete_batches += 1
                self.stdout.write(self.style.ERROR(
                    f'Delete batch {number}/{len(delete_batches)} failed'
                ))

        link_batches = list(self._batches(plan['surviving_links'], self.LINK_BATCH_SIZE))
        for number, batch in enumerate(link_batches, start=1):
            self.stdout.write(
                f'Link batch {number}/{len(link_batches)}: {len(batch)} cards'
            )
            for product, remote_id in batch:
                AliData.objects.update_or_create(
                    product=product, defaults={'id_ali': remote_id}
                )
            self.stdout.write(f'Link batch {number}/{len(link_batches)} succeeded')

        stock_batches = list(self._batches(plan['stock_updates'], self.STOCK_BATCH_SIZE))
        for number, batch in enumerate(stock_batches, start=1):
            self.stdout.write(
                f'Stock batch {number}/{len(stock_batches)}: {len(batch)} products'
            )
            if client.update_stock(data=batch) is True:
                self.stdout.write(f'Stock batch {number}/{len(stock_batches)} succeeded')
                offline_ids = [
                    update['product_id'] for update in batch
                    if update['product_id'] in plan['offline_ids']
                ]
                if offline_ids:
                    self.stdout.write(
                        f'Online batch {number}/{len(stock_batches)}: '
                        f'{len(offline_ids)} cards'
                    )
                    if client.set_online(offline_ids) is True:
                        self.stdout.write(
                            f'Online batch {number}/{len(stock_batches)} succeeded'
                        )
                    else:
                        failed_online_batches += 1
                        self.stdout.write(self.style.ERROR(
                            f'Online batch {number}/{len(stock_batches)} failed'
                        ))
            else:
                failed_stock_batches += 1
                self.stdout.write(self.style.ERROR(
                    f'Stock batch {number}/{len(stock_batches)} failed'
                ))

        self.stdout.write('Execution summary:')
        self.stdout.write(f'Deleted AliExpress cards: {deleted_cards}')
        self.stdout.write(f'Deleted local AliData links: {deleted_links}')
        self.stdout.write(f'Failed delete batches: {failed_delete_batches}')
        self.stdout.write(f'Failed stock batches: {failed_stock_batches}')
        self.stdout.write(f'Failed online batches: {failed_online_batches}')

    @staticmethod
    def _batches(items, batch_size):
        for start in range(0, len(items), batch_size):
            yield items[start:start + batch_size]
