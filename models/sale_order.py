# -*- coding: utf-8 -*-
# models/sale_order.py
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.addons.stock_lot_dimensions.models.utils.picking_cleaner import PickingLotCleaner
import logging

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    x_selected_lots = fields.Many2many('stock.quant', string='Lotes Seleccionados')
    
    # Selector de precio
    x_price_selector = fields.Selection([
        ('high', 'Precio Alto'),
        ('medium', 'Precio Medio'),
        ('custom', 'Precio Personalizado')
    ], string='Nivel de Precio', default='high', 
       help="Seleccione el nivel de precio.")

    @api.onchange('product_id')
    def _onchange_product_id_custom_price(self):
        """
        Al cambiar producto, forzamos el selector a 'High' y actualizamos precio.
        """
        if not self.product_id:
            return
        
        # Resetear selector a Alto por defecto
        self.x_price_selector = 'high'
        self._update_price_from_selector()

    @api.onchange('x_price_selector')
    def _onchange_price_selector(self):
        """Actualiza el precio cuando cambia el selector"""
        self._update_price_from_selector()

    def _update_price_from_selector(self):
        """Lógica robusta para asignar precio"""
        for line in self:
            if not line.product_id:
                continue

            # Si es personalizado, no tocamos el precio (permite edición manual)
            if line.x_price_selector == 'custom':
                continue

            # Obtener moneda: Intentar desde la orden, si no, desde el contexto, si no, Company
            currency_name = 'USD' # Default
            
            if line.order_id.pricelist_id.currency_id:
                currency_name = line.order_id.pricelist_id.currency_id.name
            elif line.env.context.get('default_pricelist_id'):
                pricelist = line.env['product.pricelist'].browse(line.env.context['default_pricelist_id'])
                currency_name = pricelist.currency_id.name
            
            template = line.product_id.product_tmpl_id
            new_price = 0.0

            # Selección de precio según moneda y nivel
            if currency_name == 'MXN':
                if line.x_price_selector == 'high':
                    new_price = template.x_price_mxn_1
                elif line.x_price_selector == 'medium':
                    new_price = template.x_price_mxn_2
            else: # USD
                if line.x_price_selector == 'high':
                    new_price = template.x_price_usd_1
                elif line.x_price_selector == 'medium':
                    new_price = template.x_price_usd_2
            
            # Aplicar precio si es mayor a 0
            if new_price > 0:
                line.price_unit = new_price

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    # Si ya tienes estos campos definidos en otro lado, esto no afecta,
    # pero asegura que el código Python los reconozca.
    x_project_id = fields.Many2one('project.project', string='Proyecto')
    x_architect_id = fields.Many2one('res.partner', string='Arquitecto')
    
    # Campo vínculo con la autorización
    x_price_authorization_id = fields.Many2one('price.authorization', string="Autorización Vinculada", copy=False, readonly=True)

    def action_request_authorization(self):
        """Botón para solicitar autorización desde Orden Manual"""
        self.ensure_one()
        
        # Guardar primero si está en modo edición sucio
        # (Odoo maneja esto en el controlador, pero validamos estado)
        if self.state not in ['draft', 'sent']:
            return

        currency_code = self.pricelist_id.currency_id.name or 'USD'
        product_prices = {}
        product_groups = {}
        has_low_price = False
        
        for line in self.order_line:
            if not line.product_id or line.display_type:
                continue
            
            template = line.product_id.product_tmpl_id
            
            # Obtener precio medio para comparar
            if currency_code == 'MXN':
                medium = template.x_price_mxn_2
            else:
                medium = template.x_price_usd_2
            
            # Si el precio es menor al medio, agregamos a la solicitud
            # (Validamos medium > 0 para evitar productos sin precio configurado)
            if medium > 0 and line.price_unit < medium:
                has_low_price = True
                pid_str = str(line.product_id.id)
                product_prices[pid_str] = line.price_unit
                
                if pid_str not in product_groups:
                    product_groups[pid_str] = {
                        'name': line.product_id.display_name,
                        'lots': [], 
                        'total_quantity': 0
                    }
                product_groups[pid_str]['total_quantity'] += line.product_uom_qty

        if not has_low_price:
            raise UserError("No se detectaron precios por debajo del nivel medio que requieran autorización.")

        # Crear la autorización
        auth_vals = {
            'seller_id': self.env.user.id,
            'operation_type': 'sale',
            'partner_id': self.partner_id.id,
            'project_id': self.x_project_id.id,
            'currency_code': currency_code,
            'notes': f"Solicitud desde Orden Manual {self.name}. {self.note or ''}",
            'sale_order_id': self.id,
            'temp_data': {
                'source': 'manual_order',
                'product_groups': product_groups,
                'architect_id': self.x_architect_id.id
            }
        }
        
        authorization = self.env['price.authorization'].create(auth_vals)
        self.x_price_authorization_id = authorization.id
        
        # Crear líneas
        for pid_str, group in product_groups.items():
            product = self.env['product.product'].browse(int(pid_str))
            requested_price = product_prices[pid_str]
            
            if currency_code == 'MXN':
                medium = product.product_tmpl_id.x_price_mxn_2
                minimum = product.product_tmpl_id.x_price_mxn_3
            else:
                medium = product.product_tmpl_id.x_price_usd_2
                minimum = product.product_tmpl_id.x_price_usd_3

            self.env['price.authorization.line'].create({
                'authorization_id': authorization.id,
                'product_id': int(pid_str),
                'quantity': group['total_quantity'],
                'lot_count': 0,
                'requested_price': requested_price,
                'authorized_price': requested_price,
                'medium_price': medium,
                'minimum_price': minimum,
            })
            
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'price.authorization',
            'res_id': authorization.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_confirm(self):
        """Valida precios al confirmar"""
        if not self.env.context.get('skip_auth_check'):
            self._check_prices_before_confirm()
            
        res = super().action_confirm()
        self._clear_auto_assigned_lots()
        return res

    def _check_prices_before_confirm(self):
        """Verificación estricta de precios"""
        for order in self:
            # Si ya tiene una autorización aprobada vinculada, permitimos confirmar
            if order.x_price_authorization_id and order.x_price_authorization_id.state == 'approved':
                continue

            currency_code = order.pricelist_id.currency_id.name or 'USD'
            violating_products = []

            for line in order.order_line:
                if not line.product_id or line.display_type or line.product_id.type == 'service':
                    continue

                template = line.product_id.product_tmpl_id
                medium_price = template.x_price_mxn_2 if currency_code == 'MXN' else template.x_price_usd_2
                
                # Tolerancia mínima para errores de punto flotante
                if medium_price > 0 and line.price_unit < (medium_price - 0.01):
                    violating_products.append(line.product_id.display_name)

            if violating_products:
                raise UserError(
                    f"⚠️ PRECIOS BAJOS DETECTADOS\n\n"
                    f"Los siguientes productos tienen un precio menor al 'Precio Medio':\n"
                    f"• {', '.join(set(violating_products))}\n\n"
                    f"Debe solicitar una autorización usando el botón 'Solicitar Autorización de Precio' en la parte superior."
                )

    # Mantener el método create_from_shopping_cart existente sin cambios...
    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, services=None, notes=None, pricelist_id=None, apply_tax=True, project_id=None, architect_id=None):
        return super().create_from_shopping_cart(partner_id, products, services, notes, pricelist_id, apply_tax, project_id, architect_id)

    def _clear_auto_assigned_lots(self):
        cleaner = PickingLotCleaner(self.env)
        for order in self:
            if order.picking_ids:
                cleaner.clear_pickings_lots(order.picking_ids)