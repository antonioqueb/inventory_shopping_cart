# -*- coding: utf-8 -*-
import math
from datetime import datetime, timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError


class StockLotHoldOrder(models.Model):
    _inherit = 'stock.lot.hold.order'

    # -------------------------------------------------------------------------
    # ALIAS EXPLÍCITO DE LÍNEAS
    # -------------------------------------------------------------------------
    # El modelo original tiene líneas con order_id, pero no necesariamente
    # expone el One2many como line_ids. Lo declaramos para que compute,
    # vista y totales funcionen de forma estable.
    line_ids = fields.One2many(
        'stock.lot.hold.order.line',
        'order_id',
        string='Líneas del Apartado',
        copy=True,
    )

    fecha_orden = fields.Datetime(
        string='Fecha de Orden',
        default=fields.Datetime.now,
    )

    fecha_expiracion = fields.Datetime(
        string='Fecha de Expiración',
        default=lambda self: self._get_default_fecha_expiracion(),
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        default=lambda self: self._default_hold_currency_id(),
    )

    x_total_m2 = fields.Float(
        string='Total m²',
        compute='_compute_hold_totals',
        store=True,
        digits='Product Unit of Measure',
    )

    x_amount_total = fields.Monetary(
        string='Total',
        compute='_compute_hold_totals',
        store=True,
        currency_field='currency_id',
    )

    @api.model
    def _default_hold_currency_id(self):
        usd = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        return usd.id or self.env.company.currency_id.id

    @api.model
    def _coerce_datetime(self, value=None):
        if not value:
            return fields.Datetime.now()

        if isinstance(value, datetime):
            return value

        return fields.Datetime.from_string(value)

    @api.model
    def _get_default_fecha_expiracion(self, fecha_orden=None):
        """
        Calcula vigencia de apartado: 5 días hábiles desde fecha_orden.
        Conserva la hora de creación.
        """
        current = self._coerce_datetime(fecha_orden)
        business_days = 0

        while business_days < 5:
            current += timedelta(days=1)
            if current.weekday() < 5:
                business_days += 1

        return current

    @api.depends(
        'line_ids',
        'line_ids.cantidad_m2',
        'line_ids.precio_unitario',
        'line_ids.x_subtotal',
    )
    def _compute_hold_totals(self):
        for order in self:
            total_m2 = 0.0
            amount_total = 0.0

            for line in order.line_ids:
                total_m2 += line.cantidad_m2 or 0.0
                amount_total += line.x_subtotal or 0.0

            order.x_total_m2 = total_m2
            order.x_amount_total = amount_total

    @api.onchange('fecha_orden')
    def _onchange_fecha_orden_set_expiration(self):
        for order in self:
            if order.fecha_orden:
                order.fecha_expiracion = order._get_default_fecha_expiracion(order.fecha_orden)

    @api.onchange('currency_id')
    def _onchange_currency_id_sync_line_prices(self):
        for order in self:
            for line in order.line_ids:
                line._update_price_from_selector()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('currency_id'):
                vals['currency_id'] = self._default_hold_currency_id()

            if not vals.get('fecha_orden'):
                vals['fecha_orden'] = fields.Datetime.now()

            if not vals.get('fecha_expiracion'):
                vals['fecha_expiracion'] = self._get_default_fecha_expiracion(vals.get('fecha_orden'))

        records = super().create(vals_list)

        # En creación manual, esto normaliza vigencia, precios y cantidades.
        # En flujo de carrito todavía no hay líneas al crear la cabecera,
        # por lo que no afecta cantidades parciales.
        records._sync_manual_defaults_and_lines()

        return records

    def write(self, vals):
        if vals.get('fecha_orden') and not vals.get('fecha_expiracion'):
            vals['fecha_expiracion'] = self._get_default_fecha_expiracion(vals.get('fecha_orden'))

        res = super().write(vals)

        if not self.env.context.get('skip_hold_order_sync'):
            if any(field in vals for field in ['fecha_orden', 'currency_id']):
                self._sync_manual_defaults_and_lines()

        return res

    def _sync_manual_defaults_and_lines(self):
        for order in self:
            vals = {}

            if not order.fecha_orden:
                vals['fecha_orden'] = fields.Datetime.now()

            if not order.fecha_expiracion:
                vals['fecha_expiracion'] = order._get_default_fecha_expiracion(
                    vals.get('fecha_orden') or order.fecha_orden
                )

            if vals:
                order.with_context(skip_hold_order_sync=True).write(vals)

            order.line_ids._sync_quantity_from_lots()
            order.line_ids._sync_price_from_selector()

    def _check_manual_price_policy(self):
        """
        Misma regla comercial de ventas:
        - Autorizadores pueden usar precio personalizado.
        - Vendedores no pueden confirmar apartados con precio personalizado manual.
        - Vendedores no pueden confirmar por debajo de precio medio.
        """
        if self.env.context.get('skip_authorization_check'):
            return

        if self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            return

        for order in self:
            violating = []

            for line in order.line_ids:
                if not line.product_id:
                    continue

                if line.product_id.type == 'service':
                    continue

                medium_price = line.x_price_2_value or 0.0

                if line.x_price_selector == 'custom':
                    violating.append(
                        f"{line.product_id.display_name}: precio personalizado no autorizado"
                    )
                    continue

                if medium_price > 0 and line.precio_unitario < (medium_price - 0.01):
                    violating.append(
                        f"{line.product_id.display_name}: "
                        f"{line.precio_unitario:.2f} menor al precio medio {medium_price:.2f}"
                    )

            if violating:
                raise UserError(
                    "🚫 APARTADO BLOQUEADO POR PRECIO\n\n"
                    "No puede confirmar este apartado porque contiene precios no autorizados:\n"
                    f"• {chr(10).join(violating)}\n\n"
                    "Use Precio 1 o Precio 2, o genere el apartado desde el carrito con autorización."
                )

    def action_recompute_hold_lines(self):
        self._sync_manual_defaults_and_lines()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Apartado recalculado',
                'message': 'Se recalcularon m², precios y totales de las líneas.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_confirm(self):
        self._sync_manual_defaults_and_lines()
        self._check_manual_price_policy()
        return super().action_confirm()


class StockLotHoldOrderLine(models.Model):
    _inherit = 'stock.lot.hold.order.line'

    x_price_selector = fields.Selection([
        ('high', 'Precio 1'),
        ('medium', 'Precio 2'),
        ('custom', 'Precio Personalizado'),
    ], string='Nivel de Precio', default='high')

    x_price_1_value = fields.Float(
        string='Monto Precio 1',
        compute='_compute_price_level_values',
        digits='Product Price',
    )

    x_price_2_value = fields.Float(
        string='Monto Precio 2',
        compute='_compute_price_level_values',
        digits='Product Price',
    )

    x_price_level_currency = fields.Char(
        string='Moneda Nivel Precio',
        compute='_compute_price_level_values',
    )

    x_can_use_custom_price = fields.Boolean(
        string='Puede usar precio personalizado',
        compute='_compute_x_can_use_custom_price',
    )

    cantidad_m2 = fields.Float(
        string='Cantidad m²',
        digits='Product Unit of Measure',
        default=0.0,
    )

    precio_unitario = fields.Float(
        string='Precio/m²',
        digits='Product Price',
        default=0.0,
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        related='order_id.currency_id',
        store=True,
        readonly=True,
    )

    x_subtotal = fields.Monetary(
        string='Total',
        compute='_compute_x_subtotal',
        store=True,
        currency_field='currency_id',
    )

    @api.depends_context('uid')
    def _compute_x_can_use_custom_price(self):
        can_use = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')

        for line in self:
            line.x_can_use_custom_price = can_use

    def _get_currency_code(self):
        self.ensure_one()

        if self.order_id and self.order_id.currency_id:
            return self.order_id.currency_id.name

        default_currency_id = self.env.context.get('default_currency_id')
        if default_currency_id:
            currency = self.env['res.currency'].browse(default_currency_id)
            if currency.exists():
                return currency.name

        return 'USD'

    @api.depends('product_id', 'order_id.currency_id')
    def _compute_price_level_values(self):
        for line in self:
            currency_code = line._get_currency_code()
            tmpl = line.product_id.product_tmpl_id if line.product_id else False

            if tmpl and currency_code == 'MXN':
                line.x_price_1_value = tmpl.x_price_mxn_1
                line.x_price_2_value = tmpl.x_price_mxn_2
            elif tmpl:
                line.x_price_1_value = tmpl.x_price_usd_1
                line.x_price_2_value = tmpl.x_price_usd_2
            else:
                line.x_price_1_value = 0.0
                line.x_price_2_value = 0.0

            line.x_price_level_currency = currency_code

    @api.depends('cantidad_m2', 'precio_unitario')
    def _compute_x_subtotal(self):
        for line in self:
            line.x_subtotal = (line.cantidad_m2 or 0.0) * (line.precio_unitario or 0.0)

    @api.model
    def _selector_from_price(self, product_id, currency_code, price):
        product = self.env['product.product'].browse(int(product_id))
        if not product.exists():
            return 'custom'

        tmpl = product.product_tmpl_id

        if currency_code == 'MXN':
            high = tmpl.x_price_mxn_1 or 0.0
            medium = tmpl.x_price_mxn_2 or 0.0
        else:
            high = tmpl.x_price_usd_1 or 0.0
            medium = tmpl.x_price_usd_2 or 0.0

        price = float(price or 0.0)

        if high and abs(price - high) <= 0.01:
            return 'high'

        if medium and abs(price - medium) <= 0.01:
            return 'medium'

        return 'custom'

    def _get_price_from_selector(self):
        self.ensure_one()

        if not self.product_id:
            return 0.0

        currency_code = self._get_currency_code()
        tmpl = self.product_id.product_tmpl_id

        if currency_code == 'MXN':
            price_high = tmpl.x_price_mxn_1 or 0.0
            price_medium = tmpl.x_price_mxn_2 or 0.0
        else:
            price_high = tmpl.x_price_usd_1 or 0.0
            price_medium = tmpl.x_price_usd_2 or 0.0

        if self.x_price_selector == 'high':
            return price_high

        if self.x_price_selector == 'medium':
            return price_medium

        return self.precio_unitario or 0.0

    def _update_price_from_selector(self):
        for line in self:
            if not line.product_id:
                continue

            if line.x_price_selector == 'custom':
                continue

            price = line._get_price_from_selector()

            if price <= 0 and line.product_id.type == 'service':
                price = getattr(line.product_id, 'lst_price', 0.0) or getattr(line.product_id, 'list_price', 0.0)

            if price > 0:
                line.precio_unitario = math.ceil(price)

    def _sync_price_from_selector(self):
        if self.env.context.get('skip_hold_line_price_sync'):
            return

        for line in self:
            if not line.product_id:
                continue

            if line.x_price_selector == 'custom':
                continue

            price = line._get_price_from_selector()

            if price <= 0 and line.product_id.type == 'service':
                price = getattr(line.product_id, 'lst_price', 0.0) or getattr(line.product_id, 'list_price', 0.0)

            if price > 0:
                price = math.ceil(price)
                if abs((line.precio_unitario or 0.0) - price) > 0.01:
                    line.with_context(skip_hold_line_price_sync=True).write({
                        'precio_unitario': price,
                    })

    def _get_quantity_from_lots(self):
        self.ensure_one()

        if self.quant_id:
            return self.quant_id.quantity or 0.0

        lots = self.env['stock.lot']

        if self.lot_ids:
            lots |= self.lot_ids

        if self.lot_id:
            lots |= self.lot_id

        if not lots:
            return 0.0

        domain = [
            ('lot_id', 'in', lots.ids),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ]

        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))

        quants = self.env['stock.quant'].search(domain)

        if quants:
            return sum(quants.mapped('quantity'))

        fallback_qty = 0.0
        for lot in lots:
            fallback_qty += getattr(lot, 'product_qty', 0.0) or 0.0

        return fallback_qty

    @api.onchange('quant_id')
    def _onchange_quant_id_set_lot_product_quantity(self):
        for line in self:
            if line.quant_id:
                line.product_id = line.quant_id.product_id
                line.lot_id = line.quant_id.lot_id

                if line.quant_id.lot_id and not line.lot_ids:
                    line.lot_ids = [(6, 0, [line.quant_id.lot_id.id])]

                line.cantidad_m2 = line.quant_id.quantity or 0.0
                line._update_price_from_selector()

    @api.onchange('product_id')
    def _onchange_product_id_set_price(self):
        for line in self:
            if not line.product_id:
                continue

            if not line.x_price_selector:
                line.x_price_selector = 'high'

            line._update_price_from_selector()

    @api.onchange('x_price_selector')
    def _onchange_x_price_selector(self):
        self._update_price_from_selector()

    @api.onchange('lot_ids', 'lot_id', 'product_id')
    def _onchange_lots_set_quantity(self):
        for line in self:
            if not line.product_id and line.lot_ids:
                first_lot = line.lot_ids[:1]
                if getattr(first_lot, 'product_id', False):
                    line.product_id = first_lot.product_id

            qty = line._get_quantity_from_lots()
            if qty:
                line.cantidad_m2 = qty

            line._update_price_from_selector()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'precio_unitario' in vals:
                vals['precio_unitario'] = math.ceil(float(vals.get('precio_unitario') or 0.0))

            if not vals.get('x_price_selector'):
                vals['x_price_selector'] = 'high'

        records = super().create(vals_list)
        records._sync_quantity_from_lots()
        records._sync_price_from_selector()

        return records

    def write(self, vals):
        if 'precio_unitario' in vals:
            vals['precio_unitario'] = math.ceil(float(vals.get('precio_unitario') or 0.0))

        res = super().write(vals)

        if any(field in vals for field in ['quant_id', 'lot_id', 'lot_ids', 'product_id']):
            self._sync_quantity_from_lots()

        if any(field in vals for field in ['product_id', 'x_price_selector', 'order_id']):
            self._sync_price_from_selector()

        return res

    def _sync_quantity_from_lots(self):
        if self.env.context.get('skip_hold_line_quantity_sync'):
            return

        for line in self:
            has_lot_source = bool(line.quant_id or line.lot_id or line.lot_ids)
            if not has_lot_source:
                continue

            qty = line._get_quantity_from_lots()

            if abs((line.cantidad_m2 or 0.0) - qty) > 0.0001:
                line.with_context(skip_hold_line_quantity_sync=True).write({
                    'cantidad_m2': qty,
                })