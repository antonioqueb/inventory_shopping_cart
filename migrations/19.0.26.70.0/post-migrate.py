"""Cierra las actividades "Autorizar quitar IVA" que quedaron colgadas.

Aprobar o rechazar la exención no cerraba la actividad de ningún
autorizador (cada uno recibió la suya). Desde esta versión el flujo las
cierra; aquí se archivan las de órdenes cuya solicitud ya no está pendiente.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

FEEDBACK = 'Cerrada por limpieza: el documento ya estaba resuelto.'


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Activity = env['mail.activity'].sudo()
    acts = Activity.search([('res_model', '=', 'sale.order'),
                            ('summary', '=ilike', 'Autorizar quitar IVA%')])
    orders = env['sale.order'].browse(list(set(acts.mapped('res_id')))).exists()
    resolved = {o.id for o in orders if o.x_iva_exempt_state != 'requested'}
    stale = acts.filtered(lambda a: a.res_id in resolved or a.res_id not in orders.ids)
    if stale:
        stale.write({'active': False, 'feedback': FEEDBACK})
    _logger.info('[inventory_shopping_cart] Quitar IVA: %s actividad(es) colgadas cerradas.', len(stale))
