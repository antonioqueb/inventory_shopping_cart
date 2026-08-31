"""La SEMILLA del MaxAvg descuenta la logística vigente (el costo migrado
SPS ya venía entregado, con logística incluida; sumarla otra vez en el
ALL-IN la duplicaba). Solo aplica a productos CON compras activadas.
Esta migración recalcula todo el catálogo con la nueva base.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    products = env['product.template'].recalculate_all_costs()
    _logger.info(
        'inventory_shopping_cart 19.0.26.38.0: recálculo masivo tras actualizar: %s productos.',
        len(products))
