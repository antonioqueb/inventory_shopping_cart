# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import logging
import traceback # Para imprimir el stacktrace completo en los logs

_logger = logging.getLogger(__name__)

# Intentar importar PickingLotCleaner de manera segura
try:
    from odoo.addons.stock_lot_dimensions.models.utils.picking_cleaner import PickingLotCleaner
except ImportError:
    PickingLotCleaner = None

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
        if not self.product_id:
            return
        self.x_price_selector = 'high'
        self._update_price_from_selector()

    @api.onchange('x_price_selector')
    def _onchange_price_selector(self):
        self._update_price_from_selector()

    def _update_price_from_selector(self):
        for line in self:
            if not line.product_id:
                continue
            if line.x_price_selector == 'custom':
                continue

            currency_name = 'USD' 
            if line.order_id.pricelist_id.currency_id:
                currency_name = line.order_id.pricelist_id.currency_id.name
            elif line.env.context.get('default_pricelist_id'):
                pricelist = line.env['product.pricelist'].browse(line.env.context['default_pricelist_id'])
                currency_name = pricelist.currency_id.name
            
            template = line.product_id.product_tmpl_id
            new_price = 0.0

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
            
            if new_price > 0:
                line.price_unit = new_price

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    x_project_id = fields.Many2one('project.project', string='Proyecto')
    x_architect_id = fields.Many2one('res.partner', string='Arquitecto')
    x_price_authorization_id = fields.Many2one('price.authorization', string="Autorización Vinculada", copy=False, readonly=True)

    def action_request_authorization(self):
        self.ensure_one()
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
            if currency_code == 'MXN':
                medium = template.x_price_mxn_2
            else:
                medium = template.x_price_usd_2
            
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
        if not self.env.context.get('skip_auth_check'):
            self._check_prices_before_confirm()
        res = super().action_confirm()
        self._clear_auto_assigned_lots()
        return res

    def _check_prices_before_confirm(self):
        for order in self:
            if order.x_price_authorization_id and order.x_price_authorization_id.state == 'approved':
                continue

            currency_code = order.pricelist_id.currency_id.name or 'USD'
            violating_products = []

            for line in order.order_line:
                if not line.product_id or line.display_type or line.product_id.type == 'service':
                    continue

                template = line.product_id.product_tmpl_id
                medium_price = template.x_price_mxn_2 if currency_code == 'MXN' else template.x_price_usd_2
                
                if medium_price > 0 and line.price_unit < (medium_price - 0.01):
                    violating_products.append(line.product_id.display_name)

            if violating_products:
                raise UserError(
                    f"⚠️ PRECIOS BAJOS DETECTADOS\n"
                    f"Productos con precio menor al 'Precio Medio':\n"
                    f"• {', '.join(set(violating_products))}\n\n"
                    f"Debe solicitar autorización."
                )

    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, services=None, notes=None, pricelist_id=None, apply_tax=True, project_id=None, architect_id=None):
        _logger.info("="*50)
        _logger.info(f"🛒 DEBUG: Inicio create_from_shopping_cart | Partner: {partner_id}")
        
        if not partner_id:
            raise UserError("El cliente es obligatorio.")
        
        try:
            # 1. Validar lista de precios
            if not pricelist_id:
                _logger.info("DEBUG: Buscando lista de precios por defecto...")
                pricelist_id = self.env['res.partner'].browse(partner_id).property_product_pricelist.id
                if not pricelist_id:
                    raise UserError("No se ha definido una lista de precios.")
            
            pricelist = self.env['product.pricelist'].browse(pricelist_id)
            currency_code = pricelist.currency_id.name
            _logger.info(f"DEBUG: Lista de precios ID: {pricelist_id}, Moneda: {currency_code}")
            
            # 2. Verificar autorización de precios
            prices_map = {}
            if products:
                for p in products:
                    prices_map[str(p['product_id'])] = p['price_unit']
            
            if not self.env.context.get('skip_auth_check'):
                auth_result = self.env['product.template'].check_price_authorization_needed(prices_map, currency_code)
                if auth_result.get('needs_authorization'):
                    _logger.info("DEBUG: Requiere autorización de precios.")
                    return {
                        'needs_authorization': True,
                        'message': 'Se detectaron precios por debajo del nivel medio. Se requiere autorización.',
                    }

            company_id = self.env.company.id
            
            # 3. Crear cabecera de la orden
            vals = {
                'partner_id': partner_id,
                'pricelist_id': pricelist_id,
                'note': notes,
                'x_project_id': project_id,
                'x_architect_id': architect_id,
                'company_id': company_id,
                'user_id': self.env.user.id,
            }
            
            _logger.info(f"DEBUG: Creando cabecera Sale Order con vals: {vals}")
            sale_order = self.create(vals)
            _logger.info(f"DEBUG: Sale Order creada ID: {sale_order.id}, Name: {sale_order.name}")
            
            # 4. Crear líneas de PRODUCTOS FÍSICOS
            if products:
                for index, product_data in enumerate(products):
                    _logger.info(f"DEBUG: Procesando Producto #{index + 1} ID: {product_data.get('product_id')}")
                    
                    product_rec = self.env['product.product'].browse(product_data['product_id'])
                    if not product_rec.exists():
                        raise UserError(f"Producto ID {product_data['product_id']} no existe.")

                    tax_ids = []
                    if apply_tax:
                        tax_ids = [(6, 0, product_rec.taxes_id.ids)]
                    else:
                        tax_ids = [(5, 0, 0)]
                    
                    selected_lots_ids = product_data.get('selected_lots', [])
                    
                    # === CORRECCIÓN CRÍTICA AQUÍ ===
                    # Obtenemos el nombre/descripción explícitamente porque create() no llama onchange
                    line_name = product_rec.get_product_multiline_description_sale() or product_rec.name
                    # Obtenemos la UoM explícitamente
                    uom_id = product_rec.uom_id.id
                    
                    line_vals = {
                        'order_id': sale_order.id,
                        'product_id': product_rec.id,
                        'name': line_name,  # <--- CAMPO OBLIGATORIO
                        'product_uom': uom_id, # <--- CAMPO OBLIGATORIO
                        'product_uom_qty': product_data['quantity'],
                        'price_unit': product_data['price_unit'],
                        'tax_ids': tax_ids,
                        'x_selected_lots': [(6, 0, selected_lots_ids)],
                        'company_id': company_id,
                        'x_price_selector': 'custom',
                    }
                    
                    _logger.info(f"DEBUG: Creando línea de producto con vals: {line_vals}")
                    try:
                        self.env['sale.order.line'].create(line_vals)
                    except Exception as e_line:
                        _logger.error(f"DEBUG: Error al crear línea de producto {product_rec.display_name}: {e_line}")
                        raise e_line

            # 5. Crear líneas de SERVICIOS
            if services:
                for index, service_data in enumerate(services):
                    _logger.info(f"DEBUG: Procesando Servicio #{index + 1} ID: {service_data.get('product_id')}")
                    
                    service_rec = self.env['product.product'].browse(service_data['product_id'])
                    
                    tax_ids = []
                    if apply_tax:
                        tax_ids = [(6, 0, service_rec.taxes_id.ids)]
                    else:
                        tax_ids = [(5, 0, 0)]
                    
                    # === CORRECCIÓN CRÍTICA AQUÍ TAMBIÉN ===
                    line_name = service_rec.get_product_multiline_description_sale() or service_rec.name
                    uom_id = service_rec.uom_id.id

                    line_vals = {
                        'order_id': sale_order.id,
                        'product_id': service_rec.id,
                        'name': line_name, # <--- CAMPO OBLIGATORIO
                        'product_uom': uom_id, # <--- CAMPO OBLIGATORIO
                        'product_uom_qty': service_data['quantity'],
                        'price_unit': service_data['price_unit'],
                        'tax_ids': tax_ids,
                        'company_id': company_id,
                        'x_price_selector': 'custom',
                    }
                    
                    _logger.info(f"DEBUG: Creando línea de servicio con vals: {line_vals}")
                    self.env['sale.order.line'].create(line_vals)

            _logger.info("DEBUG: Confirmando orden...")
            sale_order.action_confirm()
            _logger.info("DEBUG: Orden confirmada.")
            
            _logger.info("DEBUG: Asignando lotes específicos...")
            for line in sale_order.order_line:
                if line.x_selected_lots and line.product_id.type == 'product':
                    pickings = line.move_ids.mapped('picking_id')
                    if pickings:
                        # Pasamos los IDs de los lotes seleccionados
                        self._assign_specific_lots(pickings, line.product_id, line.x_selected_lots)

            _logger.info(f"✅ DEBUG: Proceso finalizado exitosamente. Orden {sale_order.name}")
            return {
                'success': True,
                'order_id': sale_order.id,
                'order_name': sale_order.name
            }
            
        except Exception as e:
            _logger.error("❌ ERROR CRÍTICO EN CREATE_FROM_SHOPPING_CART")
            _logger.error(traceback.format_exc()) # Imprime todo el stacktrace
            raise UserError(f"Error al procesar la orden: {str(e)}")

    def _assign_specific_lots(self, pickings, product, selected_quants):
        """
        Asigna lotes específicos a los movimientos de stock.
        """
        _logger.info(f"DEBUG: Asignando lotes para {product.display_name}")
        for picking in pickings:
            if picking.state in ['done', 'cancel']:
                continue
                
            moves = picking.move_ids.filtered(lambda m: m.product_id.id == product.id)
            
            for move in moves:
                _logger.info(f"DEBUG: Limpiando reservas previas en move {move.id}")
                move.move_line_ids.unlink()
                
                for quant in selected_quants:
                    if quant.product_id.id != product.id:
                        continue
                        
                    cart_item = self.env['shopping.cart'].search([
                        ('user_id', '=', self.env.user.id),
                        ('quant_id', '=', quant.id)
                    ], limit=1)
                    
                    qty_to_reserve = cart_item.quantity if cart_item else quant.quantity
                    
                    if qty_to_reserve > move.product_uom_qty:
                        _logger.warning(f"DEBUG: Ajustando reserva de {qty_to_reserve} a {move.product_uom_qty} para el move {move.id}")
                        qty_to_reserve = move.product_uom_qty

                    if qty_to_reserve <= 0:
                        continue

                    try:
                        _logger.info(f"DEBUG: Reservando lote {quant.lot_id.name}, Cantidad: {qty_to_reserve}")
                        self.env['stock.move.line'].create({
                            'move_id': move.id,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'lot_id': quant.lot_id.id,
                            'quantity': qty_to_reserve,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                            'product_uom_id': product.uom_id.id,
                        })
                    except Exception as e:
                        _logger.error(f"Error creando stock.move.line para lote {quant.lot_id.name}: {e}")
                        raise UserError(f"No se pudo asignar el lote {quant.lot_id.name}. Verifique disponibilidad.")

    def _clear_auto_assigned_lots(self):
        if PickingLotCleaner:
            cleaner = PickingLotCleaner(self.env)
            for order in self:
                if order.picking_ids:
                    cleaner.clear_pickings_lots(order.picking_ids)
        else:
            pass