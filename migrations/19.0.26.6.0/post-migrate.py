"""Borra las actividades acumuladas de autorización de PRECIOS.

Cada solicitud creaba una actividad por autorizador y, al resolverse, otra
más para el vendedor. Ninguna se cerraba sola: el reloj del systray se
llenaba de pendientes ya resueltos.

A partir de esta versión el flujo NO crea actividades (avisa por mención de
chatter, que sí notifica por inbox y correo). Esto limpia las que ya se
acumularon.

ALCANCE: SOLO las actividades cuyo documento es una solicitud de
autorización de precios (res_model = 'price.authorization'). Ese modelo no
tiene otro uso. NO se tocan las actividades sobre sale.order — ahí viven
las de autorización de DESCUENTOS, que son otro flujo y sí se cierran
solas (_discount_auth_mark_activities_done).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    actividades = env['mail.activity'].search(
        [('res_model', '=', 'price.authorization')])
    if not actividades:
        _logger.info(
            '[inventory_shopping_cart] No había actividades de autorización '
            'de precios que borrar.')
        return

    por_usuario = {}
    for act in actividades:
        login = act.user_id.login or '(sin usuario)'
        por_usuario[login] = por_usuario.get(login, 0) + 1
    _logger.info(
        '[inventory_shopping_cart] Borrando %s actividad(es) de autorización '
        'de precios: %s',
        len(actividades),
        ', '.join('%s=%s' % (k, v) for k, v in sorted(por_usuario.items())))

    actividades.unlink()
