# -*- coding: utf-8 -*-
# models/sale_order.py
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import logging

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
        """
        Actualiza el precio unitario basado en el selector y la moneda de la orden.
        """
        for line in self:
            if not line.product_id:
                continue
            if line.x_price_selector == 'custom':
                continue

            # Determinar moneda: Prioridad Orden > Contexto > Default USD
            currency_name = 'USD' 
            if line.order_id.pricelist_id.currency_id:
                currency_name = line.order_id.pricelist_id.currency_id.name
            elif line.env.context.get('default_pricelist_id'):
                pricelist = line.env['product.pricelist'].browse(line.env.context['default_pricelist_id'])
                if pricelist.exists():
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

    # ✅ NUEVO: Detectar cambio de Lista de Precios y actualizar líneas
    @api.onchange('pricelist_id')
    def _onchange_pricelist_id_custom_prices(self):
        if not self.pricelist_id:
            return
        
        # Obtener la moneda de la nueva lista seleccionada
        currency_name = self.pricelist_id.currency_id.name or 'USD'
        
        for line in self.order_line:
            # Si es precio personalizado o no hay producto, no tocar
            if not line.product_id or line.x_price_selector == 'custom':
                continue
            
            template = line.product_id.product_tmpl_id
            new_price = 0.0

            # Aplicar lógica de selección de precios con la NUEVA moneda
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
            if not pricelist_id:
                pricelist_id = self.env['res.partner'].browse(partner_id).property_product_pricelist.id
                if not pricelist_id:
                    raise UserError("No se ha definido una lista de precios.")

            pricelist = self.env['product.pricelist'].browse(pricelist_id)
            currency_code = pricelist.currency_id.name
            
            # ✅ Preparar mapa de breakdown (Desglose de lotes por producto y cantidad)
            # Esto evita depender de la tabla shopping.cart durante la asignación
            product_breakdown_map = {}
            prices_map = {}
            
            if products:
                for p in products:
                    prices_map[str(p['product_id'])] = p['price_unit']
                    
                    if 'lots_breakdown' in p and p['lots_breakdown']:
                        # Estructura: product_id -> { quant_id: quantity }
                        # ✅ Asegurar conversión a enteros para evitar fallos de llave (str vs int)
                        try:
                            q_map = {int(l['id']): float(l['quantity']) for l in p['lots_breakdown']}
                            product_breakdown_map[int(p['product_id'])] = q_map
                            _logger.info(f"DEBUG: Breakdown para producto {p['product_id']}: {q_map}")
                        except Exception as e:
                            _logger.error(f"Error parseando breakdown: {e}")

            if not self.env.context.get('skip_auth_check'):
                auth_result = self.env['product.template'].check_price_authorization_needed(prices_map, currency_code)
                if auth_result.get('needs_authorization'):
                    return {
                        'needs_authorization': True,
                        'message': 'Se detectaron precios por debajo del nivel medio. Se requiere autorización.',
                    }

            company_id = self.env.company.id
            
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
            
            if products:
                for product_data in products:
                    product_rec = self.env['product.product'].browse(product_data['product_id'])
                    
                    tax_ids = []
                    if apply_tax:
                        tax_ids = [(6, 0, product_rec.taxes_id.ids)]
                    else:
                        tax_ids = [(5, 0, 0)]
                    
                    selected_lots_ids = product_data.get('selected_lots', [])
                    
                    product_name = product_rec.get_product_multiline_description_sale() or product_rec.name
                    
                    line_vals = {
                        'order_id': sale_order.id,
                        'name': product_name,
                        'product_id': product_rec.id,
                        'product_uom_id': product_rec.uom_id.id,
                        'product_uom_qty': product_data['quantity'],
                        'price_unit': product_data['price_unit'],
                        'tax_ids': tax_ids,
                        'x_selected_lots': [(6, 0, selected_lots_ids)],
                        'company_id': company_id,
                        'x_price_selector': 'custom',
                    }
                    self.env['sale.order.line'].create(line_vals)

            if services:
                for service_data in services:
                    service_rec = self.env['product.product'].browse(service_data['product_id'])
                    
                    tax_ids = []
                    if apply_tax:
                        tax_ids = [(6, 0, service_rec.taxes_id.ids)]
                    else:
                        tax_ids = [(5, 0, 0)]
                    
                    service_name = service_rec.get_product_multiline_description_sale() or service_rec.name

                    line_vals = {
                        'order_id': sale_order.id,
                        'name': service_name,
                        'product_id': service_rec.id,
                        'product_uom_id': service_rec.uom_id.id,
                        'product_uom_qty': service_data['quantity'],
                        'price_unit': service_data['price_unit'],
                        'tax_ids': tax_ids,
                        'company_id': company_id,
                        'x_price_selector': 'custom',
                    }
                    self.env['sale.order.line'].create(line_vals)

            _logger.info("DEBUG: Confirmando orden...")
            sale_order.action_confirm()
            
            _logger.info("DEBUG: Asignando lotes específicos...")
            for line in sale_order.order_line:
                if line.x_selected_lots and line.product_id.type == 'product':
                    pickings = line.move_ids.mapped('picking_id')
                    if pickings:
                        # ✅ Pasamos el breakdown específico para este producto usando int key
                        breakdown = product_breakdown_map.get(line.product_id.id)
                        self._assign_specific_lots(pickings, line.product_id, line.x_selected_lots, breakdown=breakdown)

            return {
                'success': True,
                'order_id': sale_order.id,
                'order_name': sale_order.name
            }
            
        except Exception as e:
            _logger.error(f"❌ Error en create_from_shopping_cart: {str(e)}", exc_info=True)
            raise UserError(f"Error al procesar la orden: {str(e)}")

    def _assign_specific_lots(self, pickings, product, selected_quants, breakdown=None):
        """
        Asigna lotes específicos a los movimientos de stock.
        Distingue entre 'Placa' (Lote entero obligatorio) y 'Formato' (Cantidad específica permitida).
        """
        # Obtener el usuario real dueño de la orden para buscar en el carrito
        sale_order = pickings.mapped('sale_id')
        cart_owner_id = sale_order.user_id.id if sale_order else self.env.user.id
        
        _logger.info(f"DEBUG: Asignando lotes para {product.display_name} (ID: {product.id}).")
        if breakdown:
            _logger.info(f"DEBUG: Breakdown disponible: {breakdown}")

        for picking in pickings:
            if picking.state in ['done', 'cancel']:
                continue
                
            moves = picking.move_ids.filtered(lambda m: m.product_id.id == product.id)
            
            for move in moves:
                _logger.info(f"DEBUG: Move ID {move.id} - Demanda Inicial: {move.product_uom_qty}")
                
                # Desvincular reservas automáticas que Odoo haya hecho
                move.move_line_ids.unlink()
                
                remaining_demand = move.product_uom_qty
                
                for quant in selected_quants:
                    if quant.product_id.id != product.id:
                        continue
                        
                    if remaining_demand <= 0:
                        break

                    # ✅ NUEVA LÓGICA CONDICIONAL: Placa vs Formato
                    # Obtenemos el tipo del lote. Si no tiene, asumimos 'placa'.
                    tipo_lote = (quant.lot_id.x_tipo or 'placa').lower()
                    
                    qty_to_use = 0.0

                    if tipo_lote == 'formato':
                        # === CASO FORMATO ===
                        # Permitir cantidades específicas (parciales).
                        # 1. Prioridad: Breakdown (del Wizard)
                        if breakdown and quant.id in breakdown:
                            qty_to_use = breakdown[quant.id]
                            _logger.info(f"DEBUG: [Formato] Usando breakdown para quant {quant.id}: {qty_to_use}")
                        # 2. Prioridad: Carrito DB
                        else:
                            cart_item = self.env['shopping.cart'].search([
                                ('user_id', '=', cart_owner_id),
                                ('quant_id', '=', quant.id)
                            ], limit=1)
                            if cart_item:
                                qty_to_use = cart_item.quantity
                                _logger.info(f"DEBUG: [Formato] Usando Shopping Cart para quant {quant.id}: {qty_to_use}")
                            else:
                                qty_to_use = quant.quantity
                                _logger.info(f"DEBUG: [Formato] Fallback a Total Lote para quant {quant.id}: {qty_to_use}")
                    
                    else:
                        # === CASO PLACA (o Default) ===
                        # Forzar SIEMPRE el lote entero disponible en el stock.
                        # Ignoramos la cantidad del carrito para evitar cortes decimales accidentales.
                        qty_to_use = quant.quantity
                        _logger.info(f"DEBUG: [Placa] Forzando Lote Completo para quant {quant.id}: {qty_to_use}")

                    # ✅ CLAMP DE SEGURIDAD (TOPE)
                    # La reserva NO puede ser mayor a la demanda restante del movimiento.
                    qty_to_reserve = min(qty_to_use, remaining_demand)
                    
                    _logger.info(
                        f"DEBUG: Lote {quant.lot_id.name} ({tipo_lote}) | "
                        f"Stock: {quant.quantity} | "
                        f"Solicitado: {qty_to_use} | "
                        f"Demanda Restante: {remaining_demand} | "
                        f"-> RESERVANDO: {qty_to_reserve}"
                    )

                    if qty_to_reserve <= 0:
                        continue

                    try:
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
                        remaining_demand -= qty_to_reserve
                        
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