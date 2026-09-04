"""Focused tests of production methods without an installed Odoo runtime.

AST loading omits Odoo model registration; ORM boundaries use test doubles.
Run: python3 -m unittest discover -s tests -p 'test_cart_availability.py'
"""
import ast
import math
from pathlib import Path
from types import SimpleNamespace as Record
import unittest
from unittest.mock import Mock


MODULE = Path(__file__).resolve().parents[1]


def load_method(path, name):
    tree = ast.parse(path.read_text())
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    namespace = {'math': math}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


add_to_cart = load_method(MODULE / 'models/shopping_cart.py', 'add_to_cart')
block_reason = load_method(MODULE / 'models/stock_quant.py', '_som_cart_block_reason')
can_select_blocked = load_method(MODULE / 'models/stock_quant.py', '_som_cart_can_select_blocked')
split_rows = load_method(MODULE.parent / 'inventory_visual_enhanced/models/stock_quant.py',
                         '_iv_apply_partial_commitment_rows')


class TestCartAvailability(unittest.TestCase):
    def setUp(self):
        self.company = Record(id=1)
        self.quant = Mock(id=11, quantity=10.0, reserved_quantity=0.0,
                          company_id=self.company)
        self.quant.lot_id = Record(id=24, name='20924-1')
        self.quant.product_id = Record(id=7)
        self.quant.exists.return_value = self.quant
        self.Quant = Mock()
        self.Quant.browse.return_value = self.quant
        self.Quant._som_cart_can_select_blocked.return_value = False
        self.detail = {'id': 11, 'quantity': 10.0, 'qty_disponible': 10.0, 'cart_blocked': False}
        self.Quant.get_quant_details.return_value = [self.detail]
        self.cart = Mock()
        self.cart.env = {'stock.quant': self.Quant}

        class Environment(dict):
            companies = [self.company]
            user = Record(id=5)

        self.cart.env = Environment(self.cart.env)
        self.cart._som_active_entries_for_lots.return_value = []
        self.cart._som_pack_for_quant.return_value = None
        self.cart.search.return_value = []

    def add(self, **kwargs):
        args = dict(quant_id=11, lot_id=24, product_id=7, quantity=10.0)
        args.update(kwargs)
        return add_to_cart(self.cart, **args)

    def test_sale_without_native_reservation_is_rejected_before_create(self):
        self.detail.update(cart_blocked=True, cart_block_reason='Comprometido en V/441')
        result = self.add()
        self.assertFalse(result['success'])
        self.assertIn('20924-1', result['message'])
        self.assertIn('V/441', result['message'])
        self.cart.create.assert_not_called()
        self.cart.search.assert_not_called()

    def test_active_hold_is_rejected_even_without_native_reservation(self):
        self.detail.update(cart_blocked=True, cart_block_reason='Lote con apartado activo')
        self.assertFalse(self.add()['success'])
        self.cart.create.assert_not_called()

    def test_unavailable_or_consumed_lot_is_rejected(self):
        self.Quant.get_quant_details.return_value = []
        self.assertFalse(self.add()['success'])
        self.cart.create.assert_not_called()

    def test_free_lot_is_added(self):
        self.assertTrue(self.add()['success'])
        self.assertEqual(self.cart.create.call_args.args[0]['lot_id'], 24)

    def test_existing_cart_item_can_update(self):
        entry = Mock()
        self.cart.search.return_value = entry
        self.assertTrue(self.add(quantity=5)['success'])
        entry.write.assert_called_once_with({'quantity': 5.0})

    def test_only_free_remainder_can_be_added(self):
        self.detail.update(quantity=4.0, qty_disponible=4.0, is_available_row=True)
        self.assertFalse(self.add(quantity=5)['success'])
        self.cart.create.assert_not_called()
        self.assertTrue(self.add(quantity=4)['success'])

    def test_cart_payload_cannot_substitute_a_different_lot(self):
        self.assertFalse(self.add(lot_id=25)['success'])
        self.cart.create.assert_not_called()

    def test_invalid_quantities_do_not_enter_cart(self):
        for qty in [0, -1, float('nan'), float('inf')]:
            with self.subTest(quantity=qty):
                self.assertFalse(self.add(quantity=qty)['success'])
        self.cart.create.assert_not_called()

    def test_sales_permissions_override_location_mover(self):
        self.Quant.check_sales_permissions.return_value = True
        self.Quant.check_inventory_permissions.return_value = True
        self.Quant.check_cart_location_mover.return_value = True
        self.assertFalse(can_select_blocked(self.Quant))
        self.Quant.check_sales_permissions.return_value = False
        self.assertTrue(can_select_blocked(self.Quant))

    def test_reason_identifies_the_committing_order(self):
        self.assertEqual(block_reason({'en_orden_venta': True, 'sale_order_names': ['V/441']}),
                         'Comprometido en V/441')


class TestCommercialCommitmentRows(unittest.TestCase):
    def rows(self, kind='placa', sold=10.0, delivered=0.0, held=0.0):
        lot = Record(id=24, x_tipo=kind)
        quant = Record(id=11, lot_id=lot, location_id=Record(id=3), quantity=10.0,
                       som_hold_held_qty=lambda: held)
        sale = Record(id=8, order_id=Record(id=441), _tc_read_lot_breakdown=lambda: {'24': sold})
        maps = {'mls': {}, 'sols': {24: [sale]} if sold else {}, 'delivered': {(8, 24): delivered}}
        detail = {'id': 11, 'lot_name': '20924-1', 'quantity': 10.0,
                  'tiene_hold': bool(held), 'en_orden_venta': False}
        return split_rows(None, quant, detail, maps)

    def test_plate_is_blocked_by_commercial_assignment_without_move_lines(self):
        row, = self.rows()
        self.assertTrue(row['en_orden_venta'])
        self.assertEqual(row['sale_order_ids'], [441])
        self.assertEqual(row['qty_disponible'], 0.0)

    def test_partial_format_preserves_only_free_remainder(self):
        committed, available = self.rows(kind='formato', sold=6)
        self.assertTrue(committed['is_committed_row'])
        self.assertEqual(committed['quantity'], 6)
        self.assertFalse(available['en_orden_venta'])
        self.assertEqual(available['quantity'], 4)

    def test_partial_hold_preserves_only_free_remainder(self):
        committed, available = self.rows(kind='pieza', sold=0, held=6)
        self.assertEqual(committed['quantity'], 6)
        self.assertFalse(available['tiene_hold'])
        self.assertEqual(available['quantity'], 4)

    def test_fully_delivered_assignment_does_not_block_returned_stock(self):
        row, = self.rows(delivered=10)
        self.assertFalse(row['en_orden_venta'])
        self.assertEqual(row['qty_disponible'], 10)


if __name__ == '__main__':
    unittest.main()
