"""Recálculo masivo al actualizar: siembra la CARGA INICIAL en todo el catálogo.

La versión 26.36 corrigió el arranque de la serie MaxAvg (costo estándar
migrado × m² migrados como primer punto), pero el valor almacenado de cada
producto solo se corregía al pulsar «Actualizar costos» en su ficha. Esta
migración ejecuta ese mismo recálculo sobre TODO el catálogo (por compañía,
igual que el cron Banorte) para que nadie tenga que recalcular a mano.
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
        'inventory_shopping_cart 19.0.26.37.0: recálculo masivo tras actualizar: %s productos.',
        len(products))
