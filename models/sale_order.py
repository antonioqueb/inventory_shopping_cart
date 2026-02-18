# -*- coding: utf-8 -*-
# models/sale_order.py
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import logging
import json

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.stock_lot_dimensions.models.utils.picking_cleaner import PickingLotCleaner
except ImportError:
    PickingLotCleaner = None

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    x_selected_lots = fields.Many2many('stock.quant', string='Lotes Seleccionados', copy=True)
    x_lot_breakdown_json = fields.Json(string='Desglose de Lotes', copy=True)
    x_price_selector = fields.Selection([
        ('high', 'Precio 1'),
        ('medium', 'Precio 2'),
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
    
    # Campo para identificar si una orden es una copia de respaldo de cotización
    x_is_quote_backup = fields.Boolean(string="Es Respaldo de Cotización", default=False, copy=False)

    # 1. CREATE: Asigna secuencia COT/ al crear
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.quotation') or 'New'
        return super(SaleOrder, self).create(vals_list)

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id_custom_prices(self):
        if not self.pricelist_id:
            return
        currency_name = self.pricelist_id.currency_id.name or 'USD'
        for line in self.order_line:
            if not line.product_id or line.x_price_selector == 'custom':
                continue
            template = line.product_id.product_tmpl_id
            new_price = 0.0
            if currency_name == 'MXN':
                if line.x_price_selector == 'high':
                    new_price = template.x_price_mxn_1
                elif line.x_price_selector == 'medium':
                    new_price = template.x_price_mxn_2
            else: 
                if line.x_price_selector == 'high':
                    new_price = template.x_price_usd_1
                elif line.x_price_selector == 'medium':
                    new_price = template.x_price_usd_2
            if new_price > 0:
                line.price_unit = new_price

    def action_request_authorization(self):
        """
        Solicitar autorización de precio.
        FIX: NO duplicar la orden aquí, solo crear la autorización.
        """
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
                'sale_order_id': self.id,  # FIX: Guardar referencia a la orden existente
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

    def action_add_from_cart(self):
        self.ensure_one()
        if self.state not in ['draft', 'sent']:
            raise UserError("Solo puede agregar items en estado Borrador.")

        cart_items = self.env['shopping.cart'].search([('user_id', '=', self.env.user.id)])
        if not cart_items:
            raise UserError("Su carrito de compras está vacío.")

        grouped_items = {}
        for item in cart_items:
            already_in_line = False
            for line in self.order_line:
                if line.x_selected_lots and item.quant_id.id in line.x_selected_lots.ids:
                    already_in_line = True
                    break
            
            if already_in_line:
                continue

            prod_id = item.product_id.id
            if prod_id not in grouped_items:
                grouped_items[prod_id] = {
                    'product_obj': item.product_id,
                    'total_qty': 0.0,
                    'lots': [],
                    'breakdown': {}
                }
            
            grouped_items[prod_id]['total_qty'] += item.quantity
            grouped_items[prod_id]['lots'].append(item.quant_id.id)
            grouped_items[prod_id]['breakdown'][str(item.quant_id.id)] = item.quantity

        if not grouped_items:
            raise UserError("Los items del carrito ya se encuentran asignados en esta orden.")

        pricelist = self.pricelist_id or self.partner_id.property_product_pricelist
        if not pricelist:
             raise UserError("Defina una lista de precios en la orden antes de agregar items.")
             
        currency_code = pricelist.currency_id.name or 'USD'
        company_id = self.company_id.id or self.env.company.id
        
        lines_to_create = []
        for prod_id, data in grouped_items.items():
            product = data['product_obj']
            price_unit = 0.0
            if currency_code == 'MXN':
                price_unit = product.product_tmpl_id.x_price_mxn_1
            else:
                price_unit = product.product_tmpl_id.x_price_usd_1
            
            tax_ids = [(6, 0, product.taxes_id.ids)]
            
            lines_to_create.append({
                'order_id': self.id,
                'name': product.get_product_multiline_description_sale() or product.name,
                'product_id': prod_id,
                'product_uom_id': product.uom_id.id,
                'product_uom_qty': data['total_qty'],
                'price_unit': price_unit,
                'x_price_selector': 'high',
                'tax_ids': tax_ids,
                'x_selected_lots': [(6, 0, data['lots'])],
                'x_lot_breakdown_json': data['breakdown'],
                'company_id': company_id,
            })
        
        if lines_to_create:
            self.env['sale.order.line'].create(lines_to_create)
            self.env['shopping.cart'].clear_cart()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Items Agregados',
                    'message': 'Los productos del carrito se han agregado a la orden correctamente.',
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'} 
                }
            }
        else:
             raise UserError("No se pudieron agregar los items.")

    # ==========================================================================
    # FIX CRÍTICO: VALIDAR PRECIOS ANTES DE DUPLICAR
    # ==========================================================================
    def action_confirm(self):
        # ======================================================================
        # FIX #1: VALIDAR PRECIOS PRIMERO, ANTES de cualquier duplicación
        # Si falla la validación, no se duplica nada.
        # ======================================================================
        if not self.env.context.get('skip_auth_check'):
            self._check_prices_before_confirm()
        
        # Solo si pasó la validación, proceder con clonado y confirmación
        for order in self:
            if order.state in ['draft', 'sent'] and not order.x_is_quote_backup:
                # A) Obtener secuencia nueva para la OV
                new_ov_name = self.env['ir.sequence'].next_by_code('sale.order.confirmed')
                if not new_ov_name:
                    new_ov_name = "OV/NEW"

                # B) Crear copia como "Cotización Histórica"
                current_cot_name = order.name 
                
                copy_defaults = {
                    'name': current_cot_name,
                    'state': 'draft',
                    'origin': f"Convertido a {new_ov_name}",
                    'x_is_quote_backup': True,
                    'date_order': fields.Datetime.now()
                }
                
                backup_quote = order.copy(default=copy_defaults)
                
                # C) Transformar la orden ACTUAL en la Orden de Venta
                order.name = new_ov_name
                order.origin = current_cot_name

        # Lógica estándar de confirmación
        res = super().action_confirm()
        
        # Limpieza y asignación de lotes
        self._clear_auto_assigned_lots()
        
        for order in self:
            for line in order.order_line:
                if line.display_type or not line.product_id:
                    continue
                if line.product_id.type not in ['product', 'consu']:
                    continue
                    
                if line.x_selected_lots:
                    pickings = line.move_ids.mapped('picking_id')
                    if not pickings:
                        continue
                    
                    breakdown = line.x_lot_breakdown_json or {}
                    breakdown_int = {}
                    if breakdown:
                        try:
                            breakdown_int = {int(k): float(v) for k, v in breakdown.items()}
                        except Exception as e:
                            _logger.warning(f"Error parseando breakdown JSON en linea {line.id}: {e}")

                    order._assign_specific_lots(pickings, line.product_id, line.x_selected_lots, breakdown=breakdown_int)
        
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
        _logger.info("="*60)
        _logger.info(f"[CART-DEBUG] Inicio create_from_shopping_cart | Partner: {partner_id}")
        
        if not partner_id:
            raise UserError("El cliente es obligatorio.")
        
        try:
            if not pricelist_id:
                pricelist_id = self.env['res.partner'].browse(partner_id).property_product_pricelist.id
                if not pricelist_id:
                    raise UserError("No se ha definido una lista de precios.")

            pricelist = self.env['product.pricelist'].browse(pricelist_id)
            currency_code = pricelist.currency_id.name
            
            prices_map = {}
            if products:
                for p in products:
                    prices_map[str(p['product_id'])] = p['price_unit']

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
            _logger.info(f"[CART-DEBUG] Orden creada {sale_order.name} (ID: {sale_order.id})")
            
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
                    
                    breakdown_json = {}
                    if 'lots_breakdown' in product_data and product_data['lots_breakdown']:
                        for l in product_data['lots_breakdown']:
                            breakdown_json[str(l['id'])] = float(l['quantity'])

                    line_vals = {
                        'order_id': sale_order.id,
                        'name': product_name,
                        'product_id': product_rec.id,
                        'product_uom_id': product_rec.uom_id.id,
                        'product_uom_qty': product_data['quantity'],
                        'price_unit': product_data['price_unit'],
                        'tax_ids': tax_ids,
                        'x_selected_lots': [(6, 0, selected_lots_ids)],
                        'x_lot_breakdown_json': breakdown_json,
                        'company_id': company_id,
                        'x_price_selector': 'custom',
                    }
                    self.env['sale.order.line'].create(line_vals)

            if services:
                for service_data in services:
                    service_rec = self.env['product.product'].browse(service_data['product_id'])
                    tax_ids = [(6, 0, service_rec.taxes_id.ids)] if apply_tax else [(5, 0, 0)]
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

            # Invalidar caché
            sale_order.invalidate_recordset()
            
            _logger.info("[CART-DEBUG] Ejecutando action_confirm...")
            sale_order.action_confirm()
            
            return {
                'success': True,
                'order_id': sale_order.id,
                'order_name': sale_order.name
            }
            
        except Exception as e:
            _logger.error(f"[CART-DEBUG] ❌ Error CRÍTICO en create_from_shopping_cart: {str(e)}", exc_info=True)
            raise UserError(f"Error al procesar la orden: {str(e)}")

    def _assign_specific_lots(self, pickings, product, selected_quants, breakdown=None):
        sale_order = pickings.mapped('sale_id')
        cart_owner_id = sale_order.user_id.id if sale_order else self.env.user.id
        
        if not breakdown:
            sample_move = pickings.mapped('move_ids').filtered(lambda m: m.product_id.id == product.id)[:1]
            if sample_move and sample_move.sale_line_id and sample_move.sale_line_id.x_lot_breakdown_json:
                try:
                    raw_json = sample_move.sale_line_id.x_lot_breakdown_json
                    breakdown = {int(k): float(v) for k, v in raw_json.items()}
                except Exception as e:
                    _logger.error(f"[CART-DEBUG] Error leyendo breakdown SOL: {e}")

        _logger.info(f"[CART-DEBUG] >>> Iniciando _assign_specific_lots para {product.display_name} (ID: {product.id})")

        for picking in pickings:
            if picking.state in ['done', 'cancel']:
                continue
                
            moves = picking.move_ids.filtered(lambda m: m.product_id.id == product.id)
            
            for move in moves:
                try:
                    if move.move_line_ids:
                        move.move_line_ids.unlink()
                except Exception as e:
                    _logger.error(f"[CART-DEBUG] Error limpiando reservas: {e}")
                
                remaining_demand = move.product_uom_qty
                
                for quant in selected_quants:
                    if quant.product_id.id != product.id:
                        continue
                        
                    if remaining_demand <= 0:
                        break

                    raw_tipo = quant.lot_id.x_tipo
                    tipo_lote = (str(raw_tipo) if raw_tipo else 'placa').lower()
                    
                    qty_to_use = 0.0

                    if 'formato' in tipo_lote:
                        if breakdown and quant.id in breakdown:
                            qty_to_use = breakdown[quant.id]
                        else:
                            cart_item = self.env['shopping.cart'].search([
                                ('user_id', '=', cart_owner_id),
                                ('quant_id', '=', quant.id)
                            ], limit=1)
                            if cart_item:
                                qty_to_use = cart_item.quantity
                            else:
                                qty_to_use = quant.quantity
                    else:
                        qty_to_use = quant.quantity

                    qty_to_reserve = min(qty_to_use, remaining_demand)

                    if qty_to_reserve <= 0.001:
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
                        _logger.error(f"[CART-DEBUG] ❌ Error reservando lote {quant.lot_id.name}: {e}")

    def _clear_auto_assigned_lots(self):
        if PickingLotCleaner:
            cleaner = PickingLotCleaner(self.env)
            for order in self:
                if order.picking_ids:
                    cleaner.clear_pickings_lots(order.picking_ids)
        else:
            pass