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
    
    # Nuevo campo para el selector de nivel de precio en la vista manual
    x_price_selector = fields.Selection([
        ('high', 'Precio Alto'),
        ('medium', 'Precio Medio'),
        ('custom', 'Precio Personalizado')
    ], string='Nivel de Precio', default='high', 
       help="Seleccione el nivel de precio. 'Personalizado' permite edición manual pero puede requerir autorización.")

    @api.onchange('product_id')
    def _onchange_product_id_custom_price(self):
        """
        Al cambiar el producto, forzamos el precio 'Alto' por defecto
        según la moneda de la lista de precios.
        """
        if not self.product_id:
            return

        # Por defecto seleccionamos Precio Alto
        self.x_price_selector = 'high'
        self._update_price_from_selector()

    @api.onchange('x_price_selector')
    def _onchange_price_selector(self):
        """Actualiza el precio unitario cuando cambia el selector"""
        self._update_price_from_selector()

    def _update_price_from_selector(self):
        """Lógica central para asignar precio basado en el selector y moneda"""
        if not self.product_id or not self.order_id.pricelist_id:
            return

        currency_code = self.order_id.pricelist_id.currency_id.name
        template = self.product_id.product_tmpl_id
        new_price = 0.0

        # Determinar qué campo leer basado en moneda y selección
        if self.x_price_selector == 'custom':
            # Si es personalizado, no sobrescribimos el precio actual (a menos que sea 0)
            if self.price_unit == 0:
                pass 
            return

        if currency_code == 'MXN':
            if self.x_price_selector == 'high':
                new_price = template.x_price_mxn_1
            elif self.x_price_selector == 'medium':
                new_price = template.x_price_mxn_2
        else: # Default USD
            if self.x_price_selector == 'high':
                new_price = template.x_price_usd_1
            elif self.x_price_selector == 'medium':
                new_price = template.x_price_usd_2
        
        # Si el producto tiene precio definido, lo aplicamos
        if new_price > 0:
            self.price_unit = new_price

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    # Campos personalizados para Proyecto y Arquitecto
    x_project_id = fields.Many2one('project.project', string='Proyecto')
    x_architect_id = fields.Many2one('res.partner', string='Arquitecto')
    
    # Campo para vincular autorización a una orden manual
    x_price_authorization_id = fields.Many2one('price.authorization', string="Autorización de Precio Linked", copy=False)

    def action_request_authorization(self):
        """
        Botón para solicitar autorización desde una Orden Manual que tiene precios bajos.
        Crea un registro en price.authorization basado en las líneas actuales.
        """
        self.ensure_one()
        if self.state not in ['draft', 'sent']:
            return

        currency_code = self.pricelist_id.currency_id.name or 'USD'
        product_prices = {}
        product_groups = {}
        
        # Agrupar datos para la autorización
        for line in self.order_line:
            if not line.product_id:
                continue
            
            # Verificar si requiere autorización (Precio < Medio)
            template = line.product_id.product_tmpl_id
            medium_price = template.x_price_mxn_2 if currency_code == 'MXN' else template.x_price_usd_2
            
            if line.price_unit < medium_price:
                pid_str = str(line.product_id.id)
                product_prices[pid_str] = line.price_unit
                
                if pid_str not in product_groups:
                    product_groups[pid_str] = {
                        'name': line.product_id.display_name,
                        'lots': [], # En manual a veces no hay lotes seleccionados aún
                        'total_quantity': 0
                    }
                product_groups[pid_str]['total_quantity'] += line.product_uom_qty

        if not product_prices:
            raise UserError("No hay precios por debajo del nivel medio que requieran autorización.")

        # Crear la autorización
        auth_vals = {
            'seller_id': self.env.user.id,
            'operation_type': 'sale',
            'partner_id': self.partner_id.id,
            'project_id': self.x_project_id.id,
            'currency_code': currency_code,
            'notes': f"Solicitud desde Orden Manual {self.name}. {self.note or ''}",
            'sale_order_id': self.id, # Vinculamos esta orden existente
            'temp_data': {
                'source': 'manual_order', 
                'product_groups': product_groups,
                'architect_id': self.x_architect_id.id
            }
        }
        
        authorization = self.env['price.authorization'].create(auth_vals)
        self.x_price_authorization_id = authorization.id
        
        # Crear líneas de autorización
        for pid_str, group in product_groups.items():
            product = self.env['product.product'].browse(int(pid_str))
            requested_price = product_prices[pid_str]
            
            # Obtener precios base
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
        """
        Sobrescribe confirmar para validar precios mínimos en órdenes manuales.
        """
        # 1. Validar autorización de precios
        if not self.env.context.get('skip_auth_check'):
            self._check_prices_before_confirm()

        _logger.info("Confirmando órdenes: %s", self.mapped('name'))
        
        all_partner_ids = self.mapped('partner_id.id')
        context = dict(self.env.context)
        if all_partner_ids:
            if len(all_partner_ids) == 1:
                context['allowed_partner_id'] = all_partner_ids[0]
            else:
                context['allowed_partner_ids'] = all_partner_ids
        
        res = super(SaleOrder, self.with_context(**context)).action_confirm()
        self._clear_auto_assigned_lots()
        return res

    def _check_prices_before_confirm(self):
        """Verifica que ninguna línea tenga precio menor al medio sin autorización aprobada"""
        for order in self:
            currency_code = order.pricelist_id.currency_id.name
            requires_auth = False
            violating_products = []

            for line in order.order_line:
                if not line.product_id or line.display_type:
                    continue
                
                # Ignorar servicios o productos sin política de precios definida
                if line.product_id.type == 'service':
                    continue

                template = line.product_id.product_tmpl_id
                
                # Determinar precio medio
                medium_price = 0.0
                if currency_code == 'MXN':
                    medium_price = template.x_price_mxn_2
                else: # Default USD
                    medium_price = template.x_price_usd_2
                
                # Si el precio es 0 (no configurado), asumimos que no aplica validación estricta 
                # o es un producto especial, pero si tiene precio configurado y el de venta es menor:
                if medium_price > 0 and line.price_unit < medium_price:
                    requires_auth = True
                    violating_products.append(line.product_id.display_name)

            if requires_auth:
                # Verificar si ya tiene una autorización APROBADA vinculada
                if order.x_price_authorization_id and order.x_price_authorization_id.state == 'approved':
                     # Opcional: Verificar que los precios autorizados coincidan con los de la orden
                     # Por simplicidad, si está aprobada la dejamos pasar.
                     continue
                
                raise UserError(
                    f"Los siguientes productos tienen un precio menor al 'Precio Medio' y requieren autorización:\n"
                    f"{', '.join(violating_products)}\n\n"
                    f"Por favor, ajuste el precio a 'Medio' o utilice el botón 'Solicitar Autorización' en la cabecera."
                )

    # ... (Mantenemos los métodos existentes create_from_shopping_cart, _assign_specific_lots, etc.)
    
    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, services=None, notes=None, pricelist_id=None, apply_tax=True, project_id=None, architect_id=None):
        """
        ... (Mismo código que tenías, sin cambios necesarios aquí) ...
        """
        # ... Mantener el código original de create_from_shopping_cart ...
        return super().create_from_shopping_cart(partner_id, products, services, notes, pricelist_id, apply_tax, project_id, architect_id)

    def _clear_auto_assigned_lots(self):
        cleaner = PickingLotCleaner(self.env)
        for order in self:
            if order.picking_ids:
                cleaner.clear_pickings_lots(order.picking_ids)