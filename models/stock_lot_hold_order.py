# -*- coding: utf-8 -*-
import math
from datetime import datetime, timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError


class StockLotHoldOrder(models.Model):
    _inherit = 'stock.lot.hold.order'

    # -------------------------------------------------------------------------
    # Líneas del apartado
    # -------------------------------------------------------------------------
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

    x_hold_business_days = fields.Integer(
        string='Días hábiles del apartado',
        default=5,
        required=True,
        readonly=True,
        help='Cantidad de días hábiles que tendrá vigencia el apartado.',
    )

    x_days_to_expiration = fields.Integer(
        string='Días restantes',
        compute='_compute_x_days_to_expiration',
        store=False,
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
    def _get_default_fecha_expiracion(self, fecha_orden=None, business_days=5):
        """
        Calcula vigencia de apartado en días hábiles.
        Por defecto: 5 días hábiles desde fecha_orden.
        Conserva la hora de creación.
        """
        current = self._coerce_datetime(fecha_orden)
        business_days = int(business_days or 5)

        if business_days <= 0:
            business_days = 5

        added = 0
        while added < business_days:
            current += timedelta(days=1)
            if current.weekday() < 5:
                added += 1

        return current

    def _count_business_days_between(self, start_dt, end_dt):
        if not start_dt or not end_dt:
            return 0

        start_dt = self._coerce_datetime(start_dt)
        end_dt = self._coerce_datetime(end_dt)

        if end_dt <= start_dt:
            return 0

        current = start_dt
        count = 0

        while current.date() < end_dt.date():
            current += timedelta(days=1)
            if current.weekday() < 5:
                count += 1

        return count

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

    def _compute_x_days_to_expiration(self):
        now = fields.Datetime.now()

        for order in self:
            order.x_days_to_expiration = order._count_business_days_between(
                now,
                order.fecha_expiracion,
            )

    @api.onchange('fecha_orden', 'x_hold_business_days')
    def _onchange_fecha_orden_set_expiration(self):
        for order in self:
            if order.fecha_orden:
                order.fecha_expiracion = order._get_default_fecha_expiracion(
                    order.fecha_orden,
                    order.x_hold_business_days or 5,
                )

    @api.onchange('currency_id')
    def _onchange_currency_id_sync_line_prices(self):
        for order in self:
            order.line_ids._sync_price_from_selector()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('currency_id'):
                vals['currency_id'] = self._default_hold_currency_id()

            if not vals.get('fecha_orden'):
                vals['fecha_orden'] = fields.Datetime.now()

            if not vals.get('x_hold_business_days') or vals.get('x_hold_business_days') <= 0:
                vals['x_hold_business_days'] = 5

            if not vals.get('fecha_expiracion'):
                vals['fecha_expiracion'] = self._get_default_fecha_expiracion(
                    vals.get('fecha_orden'),
                    vals.get('x_hold_business_days') or 5,
                )

        records = super().create(vals_list)
        records._sync_manual_defaults_and_lines()
        return records

    def write(self, vals):
        if vals.get('x_hold_business_days') is not None:
            try:
                if int(vals.get('x_hold_business_days') or 0) <= 0:
                    vals['x_hold_business_days'] = 5
            except Exception:
                vals['x_hold_business_days'] = 5

        if vals.get('fecha_orden') and not vals.get('fecha_expiracion'):
            vals['fecha_expiracion'] = self._get_default_fecha_expiracion(
                vals.get('fecha_orden'),
                vals.get('x_hold_business_days') or 5,
            )

        if vals.get('x_hold_business_days') and not vals.get('fecha_expiracion'):
            for order in self:
                vals['fecha_expiracion'] = order._get_default_fecha_expiracion(
                    vals.get('fecha_orden') or order.fecha_orden or fields.Datetime.now(),
                    vals.get('x_hold_business_days') or 5,
                )
                break

        res = super().write(vals)

        if not self.env.context.get('skip_hold_order_sync'):
            if any(field in vals for field in ['fecha_orden', 'currency_id', 'x_hold_business_days']):
                self._sync_manual_defaults_and_lines()

        return res

    def _sync_manual_defaults_and_lines(self):
        for order in self:
            vals = {}

            if not order.fecha_orden:
                vals['fecha_orden'] = fields.Datetime.now()

            if not order.x_hold_business_days or order.x_hold_business_days <= 0:
                vals['x_hold_business_days'] = 5

            if not order.fecha_expiracion:
                vals['fecha_expiracion'] = order._get_default_fecha_expiracion(
                    vals.get('fecha_orden') or order.fecha_orden,
                    vals.get('x_hold_business_days') or order.x_hold_business_days or 5,
                )

            if vals:
                order.with_context(skip_hold_order_sync=True).write(vals)

            order.line_ids._sync_quantity_from_lots()
            order.line_ids._sync_price_from_selector()

    def _get_manual_price_violations(self):
        """
        Devuelve líneas de apartado manual que requieren autorización.

        Misma política comercial que el carrito:
        - Vendedor: puede elegir Precio 1, Precio 2 o capturar precio personalizado.
          Solo requiere autorización cuando el precio final queda debajo de Precio 2.
        - Precio 3 sigue restringido a autorizadores. Si un vendedor lo alcanza por
          vista heredada, también cae en autorización por estar debajo del Precio 2.
        - Autorizador: puede usar Precio 3. Solo requiere autorización si captura
          un precio por debajo de Precio 3.
        - Servicios: no participan en la escalera ni en autorización de precio.
        """
        self.ensure_one()

        violations = []
        is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')

        for line in self.line_ids:
            if not line.product_id or line.product_id.type == 'service':
                continue

            currency_code = line._get_currency_code() if hasattr(line, '_get_currency_code') else (
                self.currency_id.name if self.currency_id else 'USD'
            )
            tmpl = line.product_id.product_tmpl_id

            if currency_code == 'MXN':
                medium_price = tmpl.x_price_mxn_2 or 0.0
                minimum_price = tmpl.x_price_mxn_3 or 0.0
            else:
                medium_price = tmpl.x_price_usd_2 or 0.0
                minimum_price = tmpl.x_price_usd_3 or 0.0

            requested_price = float(line.precio_unitario or 0.0)
            selector = line.x_price_selector or 'custom'
            reason = False

            if is_authorizer:
                if minimum_price > 0 and requested_price < (minimum_price - 0.01):
                    reason = (
                        f"precio {requested_price:.2f} menor al Precio 3 "
                        f"{minimum_price:.2f}"
                    )
            else:
                if medium_price > 0 and requested_price < (medium_price - 0.01):
                    if selector == 'custom':
                        reason = (
                            f"precio personalizado {requested_price:.2f} menor al Precio 2 "
                            f"{medium_price:.2f}"
                        )
                    elif selector == 'minimum':
                        reason = (
                            f"Precio 3 requiere autorización para vendedor "
                            f"(Precio 2: {medium_price:.2f})"
                        )
                    else:
                        reason = (
                            f"precio {requested_price:.2f} menor al Precio 2 "
                            f"{medium_price:.2f}"
                        )

            if reason:
                violations.append({
                    'line': line,
                    'reason': reason,
                    'requested_price': requested_price,
                    'medium_price': medium_price,
                    'minimum_price': minimum_price,
                })

        return violations

    def _find_pending_manual_hold_authorization(self):
        self.ensure_one()

        authorizations = self.env['price.authorization'].search([
            ('operation_type', '=', 'hold'),
            ('partner_id', '=', self.partner_id.id),
            ('seller_id', '=', self.env.user.id),
            ('state', '=', 'pending'),
        ], order='create_date desc', limit=25)

        for auth in authorizations:
            temp_data = auth.temp_data or {}
            if (
                temp_data.get('source') == 'manual_hold_order'
                and int(temp_data.get('hold_order_id') or 0) == self.id
            ):
                return auth

        return self.env['price.authorization']

    def _create_manual_hold_price_authorization(self, violations):
        self.ensure_one()

        existing_auth = self._find_pending_manual_hold_authorization()
        if existing_auth:
            return existing_auth

        currency_code = self.currency_id.name if self.currency_id else 'USD'
        product_prices = {}
        product_groups = {}
        line_ids = []

        for item in violations:
            line = item['line']
            pid = line.product_id.id
            pid_str = str(pid)
            requested_price = float(item['requested_price'] or 0.0)

            product_prices[pid_str] = requested_price
            line_ids.append(line.id)

            if pid_str not in product_groups:
                product_groups[pid_str] = {
                    'name': line.product_id.display_name,
                    'lots': [],
                    'total_quantity': 0.0,
                }

            product_groups[pid_str]['total_quantity'] += line.cantidad_m2 or 0.0

            for lot in line.lot_ids:
                product_groups[pid_str]['lots'].append({
                    'id': line.quant_id.id if line.quant_id else False,
                    'lot_id': lot.id,
                    'lot_name': lot.name,
                    'quantity': line.cantidad_m2 or 0.0,
                })

        notes = self.notas or ''
        notes += f"\n\n=== SOLICITUD DESDE APARTADO MANUAL ===\n"
        notes += f"Apartado: {self.name}\n"
        notes += "Motivos:\n"
        for item in violations:
            line = item['line']
            notes += f"• {line.product_id.display_name}: {item['reason']}\n"

        auth = self.env['price.authorization'].create({
            'seller_id': self.env.user.id,
            'operation_type': 'hold',
            'partner_id': self.partner_id.id,
            'project_id': self.project_id.id if self.project_id else False,
            'currency_code': currency_code,
            'notes': notes,
            'temp_data': {
                'source': 'manual_hold_order',
                'hold_order_id': self.id,
                'hold_order_line_ids': line_ids,
                'product_prices': product_prices,
                'product_groups': product_groups,
                'architect_id': self.arquitecto_id.id if self.arquitecto_id else False,
            },
        })

        for pid_str, group in product_groups.items():
            product = self.env['product.product'].browse(int(pid_str))
            medium = product.product_tmpl_id.x_price_mxn_2 if currency_code == 'MXN' else product.product_tmpl_id.x_price_usd_2
            minimum = product.product_tmpl_id.x_price_mxn_3 if currency_code == 'MXN' else product.product_tmpl_id.x_price_usd_3

            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': int(pid_str),
                'quantity': group['total_quantity'],
                'lot_count': len(group['lots']),
                'requested_price': product_prices[pid_str],
                'authorized_price': product_prices[pid_str],
                'medium_price': medium,
                'minimum_price': minimum,
            })

        self.message_post(
            body=(
                f"Se creó la solicitud de autorización de precio "
                f"<b>{auth.name}</b> para confirmar este apartado."
            )
        )

        return auth

    def _request_manual_hold_authorization_if_needed(self):
        if self.env.context.get('skip_authorization_check'):
            return False

        self.ensure_one()
        violations = self._get_manual_price_violations()
        if not violations:
            return False

        auth = self._create_manual_hold_price_authorization(violations)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'price.authorization',
            'res_id': auth.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _check_manual_price_policy(self):
        """
        Compatibilidad: mantiene el nombre anterior, pero ahora la política
        crea solicitud de autorización en action_confirm en lugar de bloquear
        con un UserError genérico.
        """
        return True

    def action_recompute_hold_lines(self):
        self._sync_manual_defaults_and_lines()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Apartado recalculado',
                'message': 'Se recalcularon m², precios, vigencia y totales.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_confirm(self):
        self._sync_manual_defaults_and_lines()

        for order in self:
            action = order._request_manual_hold_authorization_if_needed()
            if action:
                return action

        return super().action_confirm()


class StockLotHoldOrderLine(models.Model):
    _inherit = 'stock.lot.hold.order.line'

    x_price_selector = fields.Selection([
        ('high', 'Precio 1'),
        ('medium', 'Precio 2'),
        ('minimum', 'Precio 3'),
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

    x_price_3_value = fields.Float(
        string='Monto Precio 3',
        compute='_compute_price_level_values',
        digits='Product Price',
    )

    x_price_level_currency = fields.Char(
        string='Moneda Nivel Precio',
        compute='_compute_price_level_values',
    )

    x_can_use_custom_price = fields.Boolean(
        string='Puede usar precio personalizado',
        compute='_compute_x_price_permission_flags',
    )

    x_can_use_minimum_price = fields.Boolean(
        string='Puede usar Precio 3',
        compute='_compute_x_price_permission_flags',
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
    def _compute_x_price_permission_flags(self):
        """
        El precio personalizado debe estar disponible desde el formulario manual,
        igual que en el carrito. La autorización se decide al confirmar.

        Precio 3 se mantiene visible únicamente para autorizadores.
        """
        can_use_minimum = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        for line in self:
            line.x_can_use_custom_price = True
            line.x_can_use_minimum_price = can_use_minimum

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
                line.x_price_3_value = tmpl.x_price_mxn_3
            elif tmpl:
                line.x_price_1_value = tmpl.x_price_usd_1
                line.x_price_2_value = tmpl.x_price_usd_2
                line.x_price_3_value = tmpl.x_price_usd_3
            else:
                line.x_price_1_value = 0.0
                line.x_price_2_value = 0.0
                line.x_price_3_value = 0.0

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
            minimum = tmpl.x_price_mxn_3 or 0.0
        else:
            high = tmpl.x_price_usd_1 or 0.0
            medium = tmpl.x_price_usd_2 or 0.0
            minimum = tmpl.x_price_usd_3 or 0.0

        price = float(price or 0.0)

        if high and abs(price - high) <= 0.01:
            return 'high'

        if medium and abs(price - medium) <= 0.01:
            return 'medium'

        if minimum and abs(price - minimum) <= 0.01:
            return 'minimum'

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
            price_minimum = tmpl.x_price_mxn_3 or 0.0
        else:
            price_high = tmpl.x_price_usd_1 or 0.0
            price_medium = tmpl.x_price_usd_2 or 0.0
            price_minimum = tmpl.x_price_usd_3 or 0.0

        if self.x_price_selector == 'high':
            return price_high

        if self.x_price_selector == 'medium':
            return price_medium

        if self.x_price_selector == 'minimum':
            return price_minimum

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