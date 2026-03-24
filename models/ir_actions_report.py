# -*- coding: utf-8 -*-
# models/ir_actions_report.py
from odoo import models
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """
        Intercepta la generación de PDF para bloquear impresión de sale.order
        cuando hay precios bajos y el usuario es vendedor (no autorizador).
        """
        # Obtener el reporte
        report = self._get_report(report_ref)
        
        if report and report.model == 'sale.order' and res_ids:
            is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
            
            if not is_authorizer:
                orders = self.env['sale.order'].browse(res_ids)
                for order in orders:
                    if order.x_has_low_prices:
                        # Verificar si tiene autorización aprobada
                        if order.x_price_authorization_id and order.x_price_authorization_id.state == 'approved':
                            continue
                        
                        violating = order._get_violating_products()
                        if violating:
                            raise UserError(
                                f"🚫 IMPRESIÓN BLOQUEADA - PRECIOS NO AUTORIZADOS\n\n"
                                f"No puede imprimir la orden {order.name}.\n"
                                f"Productos con precios menores al permitido:\n"
                                f"• {chr(10).join(violating)}\n\n"
                                f"Solicite autorización de precio primero."
                            )

        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)