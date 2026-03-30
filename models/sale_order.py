# -*- coding: utf-8 -*-
# models/sale_order.py
import math
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
            else:
                if line.x_price_selector == 'high':
                    new_price = template.x_price_usd_1
                elif line.x_price_selector == 'medium':
                    new_price = template.x_price_usd_2

            if new_price > 0:
                line.price_unit = new_price


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ── OVERRIDE: Quitar required de direcciones ──
    partner_invoice_id = fields.Many2one(
        'res.partner', required=False,
    )
    partner_shipping_id = fields.Many2one(
        'res.partner', required=False,
    )

    x_project_id = fields.Many2one('project.project', string='Proyecto')
    x_architect_id = fields.Many2one('res.partner', string='Arquitecto')
    x_price_authorization_id = fields.Many2one('price.authorization', string="Autorización Vinculada", copy=False, readonly=True)

    x_is_quote_backup = fields.Boolean(string="Es Respaldo de Cotización", default=False, copy=False)

    x_has_low_prices = fields.Boolean(
        string="Tiene Precios Bajos",
        compute='_compute_has_low_prices',
        store=True,
    )

    x_exchange_rate_source = fields.Selection([
        ('banorte', 'Banorte'),
        ('official', 'Diario Oficial (SAT)'),
    ], string='Fuente Tipo de Cambio', default='banorte', tracking=True)

    x_exchange_rate = fields.Float(
        string='Tipo de Cambio', digits=(12, 4),
        compute='_compute_exchange_rate', store=True, tracking=True,
    )

    x_is_usd = fields.Boolean(string='Es USD', compute='_compute_is_usd', store=True)

    @api.onchange('partner_id')
    def _onchange_partner_id_keep_addresses_empty(self):
        """
        Mantiene vacíos los campos de dirección de factura y entrega
        al seleccionar el cliente, evitando que Odoo rellene ambos con
        el mismo partner cuando no existen direcciones hijas específicas.
        """
        res = super()._onchange_partner_id()
        for order in self:
            order.partner_invoice_id = False
            order.partner_shipping_id = False
        return res

    @api.depends('pricelist_id', 'pricelist_id.currency_id')
    def _compute_is_usd(self):
        for order in self:
            order.x_is_usd = bool(order.pricelist_id and order.pricelist_id.currency_id and order.pricelist_id.currency_id.name == 'USD')

    @api.depends('x_exchange_rate_source')
    def _compute_exchange_rate(self):
        banorte_rate = self._get_banorte_rate()
        official_rate = self._get_official_rate()
        for order in self:
            order.x_exchange_rate = official_rate if order.x_exchange_rate_source == 'official' else banorte_rate

    def _get_banorte_rate(self):
        try:
            rate = float(self.env['ir.config_parameter'].sudo().get_param('banorte.last_rate', '0'))
            if rate > 0:
                return rate
        except (ValueError, TypeError):
            pass
        return self._get_official_rate()

    def _get_official_rate(self):
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        cc = self.env.company.currency_id
        if usd and cc and usd != cc:
            return usd._convert(1.0, cc, self.env.company, fields.Date.today())
        return 1.0

    @api.depends('order_line.price_unit', 'order_line.product_id', 'pricelist_id', 'x_price_authorization_id', 'x_price_authorization_id.state')
    def _compute_has_low_prices(self):
        for order in self:
            if order.x_price_authorization_id and order.x_price_authorization_id.state == 'approved':
                order.x_has_low_prices = False
                continue
            currency_code = order.pricelist_id.currency_id.name or 'USD' if order.pricelist_id else 'USD'
            has_low = False
            for line in order.order_line:
                if not line.product_id or line.display_type or line.product_id.type == 'service':
                    continue
                tmpl = line.product_id.product_tmpl_id
                medium = tmpl.x_price_mxn_2 if currency_code == 'MXN' else tmpl.x_price_usd_2
                if medium > 0 and line.price_unit < (medium - 0.01):
                    has_low = True
                    break
            order.x_has_low_prices = has_low

    def _get_violating_products(self):
        self.ensure_one()
        currency_code = self.pricelist_id.currency_id.name or 'USD' if self.pricelist_id else 'USD'
        violating = []
        for line in self.order_line:
            if not line.product_id or line.display_type or line.product_id.type == 'service':
                continue
            tmpl = line.product_id.product_tmpl_id
            medium = tmpl.x_price_mxn_2 if currency_code == 'MXN' else tmpl.x_price_usd_2
            if medium > 0 and line.price_unit < (medium - 0.01):
                violating.append(f"{line.product_id.display_name} (Precio: {line.price_unit:.2f}, Medio: {medium:.2f})")
        return violating

    def _check_seller_low_price_block(self, action_name="realizar esta acción"):
        for order in self:
            if not order.x_has_low_prices:
                continue
            if order.x_price_authorization_id and order.x_price_authorization_id.state == 'approved':
                continue
            if self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
                continue
            violating = order._get_violating_products()
            if violating:
                raise UserError(
                    f"🚫 ACCIÓN BLOQUEADA - PRECIOS NO AUTORIZADOS\n\n"
                    f"No puede {action_name} la orden {order.name}.\n"
                    f"Productos con precios menores al permitido:\n"
                    f"• {chr(10).join(violating)}\n\n"
                    f"Solicite autorización de precio primero."
                )

    def action_quotation_send(self):
        self._check_seller_low_price_block("enviar")
        return super().action_quotation_send()

    def action_confirm(self):
        if not self.env.context.get('skip_auth_check'):
            self._check_seller_low_price_block("confirmar")

        for order in self:
            if order.state in ['draft', 'sent'] and not order.x_is_quote_backup:
                new_ov_name = self.env['ir.sequence'].next_by_code('sale.order.confirmed') or "OV/NEW"
                current_cot_name = order.name
                order.copy(default={
                    'name': current_cot_name,
                    'state': 'draft',
                    'origin': f"Convertido a {new_ov_name}",
                    'x_is_quote_backup': True,
                    'date_order': fields.Datetime.now()
                })
                order.name = new_ov_name
                order.origin = current_cot_name

        res = super().action_confirm()
        self._clear_auto_assigned_lots()

        for order in self:
            for line in order.order_line:
                if line.display_type or not line.product_id or line.product_id.type not in ['product', 'consu']:
                    continue
                if line.x_selected_lots:
                    pickings = line.move_ids.mapped('picking_id')
                    if not pickings:
                        continue
                    breakdown_int = {}
                    if line.x_lot_breakdown_json:
                        try:
                            breakdown_int = {int(k): float(v) for k, v in line.x_lot_breakdown_json.items()}
                        except Exception as e:
                            _logger.warning(f"Error parseando breakdown: {e}")
                    order._assign_specific_lots(
                        pickings,
                        line.product_id,
                        line.x_selected_lots,
                        breakdown=breakdown_int
                    )
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.quotation') or 'New'

            # Forzar que nazcan vacíos si no fueron enviados explícitamente
            if 'partner_invoice_id' not in vals:
                vals['partner_invoice_id'] = False
            if 'partner_shipping_id' not in vals:
                vals['partner_shipping_id'] = False

        return super().create(vals_list)

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id_custom_prices(self):
        if not self.pricelist_id:
            return
        currency_name = self.pricelist_id.currency_id.name or 'USD'
        for line in self.order_line:
            if not line.product_id or line.x_price_selector == 'custom':
                continue
            tmpl = line.product_id.product_tmpl_id
            new_price = 0.0
            if currency_name == 'MXN':
                new_price = tmpl.x_price_mxn_1 if line.x_price_selector == 'high' else tmpl.x_price_mxn_2
            else:
                new_price = tmpl.x_price_usd_1 if line.x_price_selector == 'high' else tmpl.x_price_usd_2
            if new_price > 0:
                line.price_unit = new_price

    def action_request_authorization(self):
        self.ensure_one()
        if self.state not in ['draft', 'sent']:
            return
        currency_code = self.pricelist_id.currency_id.name or 'USD'
        product_prices, product_groups, has_low = {}, {}, False

        for line in self.order_line:
            if not line.product_id or line.display_type:
                continue
            tmpl = line.product_id.product_tmpl_id
            medium = tmpl.x_price_mxn_2 if currency_code == 'MXN' else tmpl.x_price_usd_2
            if medium > 0 and line.price_unit < (medium - 0.01):
                has_low = True
                pid_str = str(line.product_id.id)
                product_prices[pid_str] = line.price_unit
                if pid_str not in product_groups:
                    product_groups[pid_str] = {
                        'name': line.product_id.display_name,
                        'lots': [],
                        'total_quantity': 0
                    }
                product_groups[pid_str]['total_quantity'] += line.product_uom_qty

        if not has_low:
            raise UserError("No se detectaron precios por debajo del nivel medio.")

        auth = self.env['price.authorization'].create({
            'seller_id': self.env.user.id,
            'operation_type': 'sale',
            'partner_id': self.partner_id.id,
            'project_id': self.x_project_id.id,
            'currency_code': currency_code,
            'notes': f"Solicitud desde Orden Manual {self.name}. {self.note or ''}",
            'sale_order_id': self.id,
            'temp_data': {
                'source': 'manual_order',
                'sale_order_id': self.id,
                'product_groups': product_groups,
                'architect_id': self.x_architect_id.id
            }
        })
        self.x_price_authorization_id = auth.id

        for pid_str, group in product_groups.items():
            product = self.env['product.product'].browse(int(pid_str))
            medium = product.product_tmpl_id.x_price_mxn_2 if currency_code == 'MXN' else product.product_tmpl_id.x_price_usd_2
            minimum = product.product_tmpl_id.x_price_mxn_3 if currency_code == 'MXN' else product.product_tmpl_id.x_price_usd_3
            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': int(pid_str),
                'quantity': group['total_quantity'],
                'lot_count': 0,
                'requested_price': product_prices[pid_str],
                'authorized_price': product_prices[pid_str],
                'medium_price': medium,
                'minimum_price': minimum,
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'price.authorization',
            'res_id': auth.id,
            'view_mode': 'form',
            'target': 'current'
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
            if any(line.x_selected_lots and item.quant_id.id in line.x_selected_lots.ids for line in self.order_line):
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
            raise UserError("Defina una lista de precios en la orden.")
        currency_code = pricelist.currency_id.name or 'USD'
        company_id = self.company_id.id or self.env.company.id

        lines_to_create = []
        for prod_id, data in grouped_items.items():
            product = data['product_obj']
            price_unit = product.product_tmpl_id.x_price_mxn_1 if currency_code == 'MXN' else product.product_tmpl_id.x_price_usd_1
            lines_to_create.append({
                'order_id': self.id,
                'name': product.get_product_multiline_description_sale() or product.name,
                'product_id': prod_id,
                'product_uom_id': product.uom_id.id,
                'product_uom_qty': data['total_qty'],
                'price_unit': price_unit,
                'x_price_selector': 'high',
                'tax_ids': [(6, 0, product.taxes_id.ids)],
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
                    'message': 'Los productos del carrito se han agregado correctamente.',
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'}
                }
            }
        raise UserError("No se pudieron agregar los items.")

    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, services=None, notes=None, pricelist_id=None, apply_tax=True, project_id=None, architect_id=None):
        if not partner_id:
            raise UserError("El cliente es obligatorio.")
        try:
            if not pricelist_id:
                pricelist_id = self.env['res.partner'].browse(partner_id).property_product_pricelist.id
                if not pricelist_id:
                    raise UserError("No se ha definido una lista de precios.")

            pricelist = self.env['product.pricelist'].browse(pricelist_id)
            currency_code = pricelist.currency_id.name
            prices_map = {str(p['product_id']): p['price_unit'] for p in (products or [])}
            is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')

            if not self.env.context.get('skip_auth_check') and not is_authorizer:
                auth_result = self.env['product.template'].check_price_authorization_needed(prices_map, currency_code)
                if auth_result.get('needs_authorization'):
                    return {
                        'needs_authorization': True,
                        'message': 'Se detectaron precios por debajo del nivel medio. Se requiere autorización.'
                    }

            company_id = self.env.company.id
            sale_order = self.with_context(skip_auth_check=True).create({
                'partner_id': partner_id,
                'pricelist_id': pricelist_id,
                'note': notes,
                'x_project_id': project_id,
                'x_architect_id': architect_id,
                'company_id': company_id,
                'user_id': self.env.user.id,
            })

            for pd in (products or []):
                rec = self.env['product.product'].browse(pd['product_id'])
                tax_ids = [(6, 0, rec.taxes_id.ids)] if apply_tax else [(5, 0, 0)]
                breakdown_json = {
                    str(l['id']): float(l['quantity']) for l in pd.get('lots_breakdown', [])
                } if pd.get('lots_breakdown') else {}
                self.env['sale.order.line'].create({
                    'order_id': sale_order.id,
                    'name': rec.get_product_multiline_description_sale() or rec.name,
                    'product_id': rec.id,
                    'product_uom_id': rec.uom_id.id,
                    'product_uom_qty': pd['quantity'],
                    'price_unit': pd['price_unit'],
                    'tax_ids': tax_ids,
                    'x_selected_lots': [(6, 0, pd.get('selected_lots', []))],
                    'x_lot_breakdown_json': breakdown_json,
                    'company_id': company_id,
                    'x_price_selector': 'custom',
                })

            for sd in (services or []):
                rec = self.env['product.product'].browse(sd['product_id'])
                tax_ids = [(6, 0, rec.taxes_id.ids)] if apply_tax else [(5, 0, 0)]
                self.env['sale.order.line'].create({
                    'order_id': sale_order.id,
                    'name': rec.get_product_multiline_description_sale() or rec.name,
                    'product_id': rec.id,
                    'product_uom_id': rec.uom_id.id,
                    'product_uom_qty': sd['quantity'],
                    'price_unit': sd['price_unit'],
                    'tax_ids': tax_ids,
                    'company_id': company_id,
                    'x_price_selector': 'custom',
                })

            sale_order.invalidate_recordset()
            sale_order.with_context(skip_auth_check=True).action_confirm()
            return {
                'success': True,
                'order_id': sale_order.id,
                'order_name': sale_order.name
            }

        except Exception as e:
            _logger.error(f"Error en create_from_shopping_cart: {str(e)}", exc_info=True)
            raise UserError(f"Error al procesar la orden: {str(e)}")

    def _assign_specific_lots(self, pickings, product, selected_quants, breakdown=None):
        sale_order = pickings.mapped('sale_id')
        cart_owner_id = sale_order.user_id.id if sale_order else self.env.user.id

        if not breakdown:
            sample_move = pickings.mapped('move_ids').filtered(lambda m: m.product_id.id == product.id)[:1]
            if sample_move and sample_move.sale_line_id and sample_move.sale_line_id.x_lot_breakdown_json:
                try:
                    breakdown = {int(k): float(v) for k, v in sample_move.sale_line_id.x_lot_breakdown_json.items()}
                except Exception:
                    pass

        for picking in pickings:
            if picking.state in ['done', 'cancel']:
                continue
            for move in picking.move_ids.filtered(lambda m: m.product_id.id == product.id):
                try:
                    if move.move_line_ids:
                        move.move_line_ids.unlink()
                except Exception:
                    pass

                remaining = move.product_uom_qty
                for quant in selected_quants:
                    if quant.product_id.id != product.id or remaining <= 0:
                        continue
                    tipo = (str(quant.lot_id.x_tipo) if quant.lot_id.x_tipo else 'placa').lower()
                    if 'formato' in tipo:
                        qty = breakdown.get(quant.id, 0) if breakdown and quant.id in breakdown else (
                            self.env['shopping.cart'].search([
                                ('user_id', '=', cart_owner_id),
                                ('quant_id', '=', quant.id)
                            ], limit=1).quantity or quant.quantity
                        )
                    else:
                        qty = quant.quantity
                    reserve = min(qty, remaining)
                    if reserve <= 0.001:
                        continue
                    try:
                        self.env['stock.move.line'].create({
                            'move_id': move.id,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'lot_id': quant.lot_id.id,
                            'quantity': reserve,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                            'product_uom_id': product.uom_id.id,
                        })
                        remaining -= reserve
                    except Exception as e:
                        _logger.error(f"Error reservando lote {quant.lot_id.name}: {e}")

    def _clear_auto_assigned_lots(self):
        if PickingLotCleaner:
            cleaner = PickingLotCleaner(self.env)
            for order in self:
                if order.picking_ids:
                    cleaner.clear_pickings_lots(order.picking_ids)