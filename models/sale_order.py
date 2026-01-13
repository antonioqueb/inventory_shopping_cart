# -*- coding: utf-8 -*-
# models/sale_order.py
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
# Asegúrate de que esta importación sea correcta según tu estructura de carpetas
# Si PickingLotCleaner está en stock_lot_dimensions, verifica la ruta
try:
    from odoo.addons.stock_lot_dimensions.models.utils.picking_cleaner import PickingLotCleaner
except ImportError:
    PickingLotCleaner = None
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
    
    x_project_id = fields.Many2one('project.project', string='Proyecto')
    x_architect_id = fields.Many2one('res.partner', string='Arquitecto')
    
    # Campo vínculo con la autorización
    x_price_authorization_id = fields.Many2one('price.authorization', string="Autorización Vinculada", copy=False, readonly=True)

    def action_request_authorization(self):
        """Botón para solicitar autorización desde Orden Manual"""
        self.ensure_one()
        
        # Guardar primero si está en modo edición sucio
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
            if medium > 0 and line.price_unit < (medium - 0.01):
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

    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, services=None, notes=None, pricelist_id=None, apply_tax=True, project_id=None, architect_id=None):
        """
        Crea una orden de venta directamente desde el carrito de compras.
        Implementa toda la lógica de creación en lugar de llamar a super().
        """
        if not partner_id:
            raise UserError("El cliente es obligatorio.")
        
        # Validar lista de precios
        if not pricelist_id:
            # Intentar obtener una por defecto
            pricelist_id = self.env['res.partner'].browse(partner_id).property_product_pricelist.id
            if not pricelist_id:
                raise UserError("No se ha definido una lista de precios.")

        # Verificar autorizaciones necesarias (doble check por seguridad)
        currency_code = self.env['product.pricelist'].browse(pricelist_id).currency_id.name
        
        # Diccionario simple de precios solicitados para validación rápida
        prices_map = {}
        if products:
            for p in products:
                prices_map[str(p['product_id'])] = p['price_unit']
        
        # Si no se pasó explícitamente skip_auth_check en el contexto, verificamos
        if not self.env.context.get('skip_auth_check'):
            auth_result = self.env['product.template'].check_price_authorization_needed(prices_map, currency_code)
            if auth_result.get('needs_authorization'):
                # Devolvemos estructura especial para que el frontend abra el wizard
                return {
                    'needs_authorization': True,
                    'message': 'Se detectaron precios por debajo del nivel medio. Se requiere autorización.',
                    # El frontend deberá volver a llamar a la creación de autorización si recibe esto
                }

        company_id = self.env.company.id
        
        # 1. Crear Cabecera de Orden
        vals = {
            'partner_id': partner_id,
            'pricelist_id': pricelist_id,
            'note': notes,
            'x_project_id': project_id,
            'x_architect_id': architect_id,
            'company_id': company_id,
            'user_id': self.env.user.id,
        }
        
        sale_order = self.create(vals)
        
        # 2. Crear líneas de Productos Físicos
        if products:
            for product_data in products:
                product_rec = self.env['product.product'].browse(product_data['product_id'])
                
                # Lógica de Impuestos
                tax_ids = []
                if apply_tax:
                    tax_ids = [(6, 0, product_rec.taxes_id.ids)]
                else:
                    tax_ids = [(5, 0, 0)] # Limpiar impuestos
                
                # Preparar lotes seleccionados
                selected_lots_ids = product_data.get('selected_lots', [])
                
                line_vals = {
                    'order_id': sale_order.id,
                    'product_id': product_rec.id,
                    'product_uom_qty': product_data['quantity'],
                    'price_unit': product_data['price_unit'],
                    'tax_ids': tax_ids,
                    'x_selected_lots': [(6, 0, selected_lots_ids)], # Asignar los IDs de quants
                    'company_id': company_id,
                    'x_price_selector': 'custom', # Marcar como personalizado para que no se sobrescriba
                }
                self.env['sale.order.line'].create(line_vals)

        # 3. Crear líneas de Servicios
        if services:
            for service_data in services:
                service_rec = self.env['product.product'].browse(service_data['product_id'])
                
                tax_ids = []
                if apply_tax:
                    tax_ids = [(6, 0, service_rec.taxes_id.ids)]
                else:
                    tax_ids = [(5, 0, 0)]
                
                line_vals = {
                    'order_id': sale_order.id,
                    'product_id': service_rec.id,
                    'product_uom_qty': service_data['quantity'],
                    'price_unit': service_data['price_unit'],
                    'tax_ids': tax_ids,
                    'company_id': company_id,
                    'x_price_selector': 'custom',
                }
                self.env['sale.order.line'].create(line_vals)

        # 4. Confirmar la orden (Genera Picking)
        sale_order.action_confirm()
        
        # 5. Asignar Lotes Específicos al Picking Generado
        for line in sale_order.order_line:
            if line.x_selected_lots and line.product_id.type == 'product':
                # Buscar pickings asociados a esta línea
                pickings = line.move_ids.mapped('picking_id')
                if pickings:
                    # Llamar al método auxiliar de asignación
                    self._assign_specific_lots(pickings, line.product_id, line.x_selected_lots)

        return {
            'success': True,
            'order_id': sale_order.id,
            'order_name': sale_order.name
        }

    def _assign_specific_lots(self, pickings, product, selected_quants):
        """
        Asigna lotes específicos a los movimientos de stock en los pickings.
        
        Args:
            pickings: Recordset de stock.picking
            product: Recordset del producto
            selected_quants: Recordset de stock.quant seleccionados en el carrito
        """
        for picking in pickings:
            # Solo procesar si el picking no está hecho o cancelado
            if picking.state in ['done', 'cancel']:
                continue
                
            # Buscar movimientos para este producto
            moves = picking.move_ids.filtered(lambda m: m.product_id.id == product.id)
            
            for move in moves:
                # Limpiar líneas de movimiento existentes (reservas automáticas)
                # Esto es crucial para que Odoo no intente reservar otros lotes
                move.move_line_ids.unlink()
                
                # Crear líneas de movimiento manuales para cada lote seleccionado
                for quant in selected_quants:
                    # Verificar que el quant pertenezca al producto (seguridad)
                    if quant.product_id.id != product.id:
                        continue
                        
                    # Crear la asignación
                    self.env['stock.move.line'].create({
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'lot_id': quant.lot_id.id,
                        'quantity': quant.quantity, # Usar la cantidad disponible en el quant/carrito
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'product_uom_id': product.uom_id.id,
                    })

    def _clear_auto_assigned_lots(self):
        if PickingLotCleaner:
            cleaner = PickingLotCleaner(self.env)
            for order in self:
                if order.picking_ids:
                    cleaner.clear_pickings_lots(order.picking_ids)
        else:
            _logger.warning("PickingLotCleaner no está disponible. No se limpiaron asignaciones automáticas.")