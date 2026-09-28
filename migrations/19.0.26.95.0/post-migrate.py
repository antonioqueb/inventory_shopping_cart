"""Regla nueva (27 sep 2026): autorizar un producto ya no libera a los demás
de la orden. Decisión del cliente: RESPETAR lo existente.

Órdenes activas con autorización aprobada que tienen OTROS productos por
debajo del mínimo que nunca se autorizaron: sus precios actuales se guardan
como autorizados. No se bloquean hoy, pero desde ahora no pueden bajar más
sin re-autorización. Todo lo nuevo sigue la regla completa.

Corre después de la carga del módulo (la recalculación de banderas del
-u ya las marcó): escribir los precios autorizados vuelve a recalcularlas.
"""
import logging

from markupsafe import Markup

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Auth = env['price.authorization']
    orders = env['sale.order'].search([
        ('state', 'in', ('draft', 'sent', 'sale')),
        ('x_authorized_floor_json', '!=', False),
    ])
    kept = 0
    for order in orders:
        approved = (order.x_price_authorization_id.state == 'approved') or bool(Auth.search_count([
            ('sale_order_id', '=', order.id), ('state', '=', 'approved')], limit=1))
        if not approved:
            continue
        try:
            items = [i for i in order._som_price_auth_lines() if not i['reauth']]
        except Exception:  # noqa: BLE001 — una orden rara no detiene el -u
            _logger.exception('[PRECIOS] No se pudo evaluar %s', order.name)
            continue
        if not items:
            continue
        floors = dict(order.x_authorized_floor_json or {})
        currency = order.pricelist_id.currency_id.name if order.pricelist_id else None
        if floors.get('_cur') and currency and floors['_cur'] != currency:
            continue
        added = {}
        for item in items:
            pid = str(item['line'].product_id.id)
            price = float(item['line'].price_unit or 0.0)
            added[pid] = min(price, added.get(pid, price))
        floors.update(added)
        if currency:
            floors['_cur'] = currency
        order.with_context(som_price_auth_auto=True, tracking_disable=True).write(
            {'x_authorized_floor_json': floors})
        names = ', '.join(i['line'].product_id.display_name for i in items)
        order.message_post(body=Markup(
            '<p>🔒 Regla de autorización por producto activada: los precios actuales de '
            '<b>%s</b> se conservan como autorizados (la orden ya tenía una autorización '
            'aprobada). Bajarlos de aquí pedirá re-autorización.</p>') % names,
            message_type='notification', subtype_xmlid='mail.mt_note')
        kept += 1
    _logger.info('[PRECIOS] Regla por producto: %s órdenes existentes conservan sus precios.', kept)
