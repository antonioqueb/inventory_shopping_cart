"""TC de origen congelado en apartados y órdenes de venta.

Antes el TC se calculaba en vivo (Banorte/DOF del día) y cambiaba a diario.
Aquí se rellena x_frozen_exchange_rate de lo ya existente:
- Apartados: TC de su fuente a la fecha del apartado.
- Órdenes: TC congelado en entrega > TC al confirmar > TC del apartado de
  origen > TC de su fuente a la fecha de creación.
Las órdenes con TC manual y las canceladas no se tocan.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    SaleOrder = env['sale.order']

    holds = env['stock.lot.hold.order'].with_context(active_test=False).search([
        ('state', '!=', 'cancel'),
        '|', ('x_frozen_exchange_rate', '=', False),
        ('x_frozen_exchange_rate', '=', 0),
    ])
    hold_rate_by_so = {}
    for hold in holds:
        when = hold.fecha_orden or hold.create_date
        rate = SaleOrder._som_exchange_rate_at(
            hold.x_exchange_rate_source or 'banorte', when,
            hold.company_id or env.company)
        cr.execute("UPDATE stock_lot_hold_order SET x_frozen_exchange_rate = %s "
                   "WHERE id = %s", (rate, hold.id))
        if hold.sale_order_id:
            hold_rate_by_so[hold.sale_order_id.id] = (
                rate, hold.x_exchange_rate_source or 'banorte')

    orders = SaleOrder.with_context(active_test=False).search([
        ('state', '!=', 'cancel'),
        ('x_exchange_rate_source', '!=', 'manual'),
        '|', ('x_frozen_exchange_rate', '=', False),
        ('x_frozen_exchange_rate', '=', 0),
    ])
    for order in orders:
        rate = order.x_delivery_exchange_rate or order.x_confirm_exchange_rate
        if not rate and order.id in hold_rate_by_so:
            rate = hold_rate_by_so[order.id][0]
        if not rate:
            rate = SaleOrder._som_exchange_rate_at(
                order.x_exchange_rate_source or 'banorte', order.create_date,
                order.company_id or env.company)
        cr.execute("UPDATE sale_order SET x_frozen_exchange_rate = %s "
                   "WHERE id = %s", (rate, order.id))

    _logger.info('[inventory_shopping_cart] TC de origen: %s apartado(s), '
                 '%s orden(es) rellenados.', len(holds), len(orders))
