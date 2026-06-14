# -*- coding: utf-8 -*-
import math
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


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
        string='Subtotal',
        compute='_compute_hold_totals',
        store=True,
        currency_field='currency_id',
    )

    x_amount_tax = fields.Monetary(
        string='Impuestos',
        compute='_compute_hold_totals',
        store=True,
        currency_field='currency_id',
    )

    x_amount_total_taxed = fields.Monetary(
        string='Total',
        compute='_compute_hold_totals',
        store=True,
        currency_field='currency_id',
    )

    # -------------------------------------------------------------------------
    # Control de renovaciones (revivir apartado)
    # -------------------------------------------------------------------------
    x_renew_count = fields.Integer(
        string='Veces renovado',
        default=0,
        copy=False,
        readonly=True,
        help='Número de veces que se ha revivido (renovado) este apartado.',
    )

    x_can_renew = fields.Boolean(
        string='Puede renovar',
        compute='_compute_x_can_renew',
        help='Los autorizadores de precios pueden revivir el apartado sin '
             'límite; un vendedor solo puede hacerlo una vez. Después debe '
             'crear un apartado nuevo desde cero.',
    )

    @api.depends('x_renew_count')
    def _compute_x_can_renew(self):
        is_authorizer = self.env.user.has_group(
            'inventory_shopping_cart.group_price_authorizer'
        )
        for order in self:
            order.x_can_renew = is_authorizer or order.x_renew_count < 1

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
        'line_ids.product_id',
        'line_ids.product_id.taxes_id',
        'partner_id',
        'partner_id.property_account_position_id',
        'currency_id',
    )
    def _compute_hold_totals(self):
        for order in self:
            total_m2 = 0.0
            amount_untaxed = 0.0
            amount_tax = 0.0

            company = order.company_id or self.env.company
            currency = order.currency_id or company.currency_id
            fpos = order.partner_id.property_account_position_id

            for line in order.line_ids:
                qty = line.cantidad_m2 or 0.0
                price = line.precio_unitario or 0.0
                total_m2 += qty

                # Impuestos reales configurados en el producto (taxes de venta),
                # filtrados por compañía y mapeados por la posición fiscal del cliente.
                taxes = self.env['account.tax']
                if line.product_id:
                    taxes = line.product_id.taxes_id.filtered(
                        lambda t: t.company_id == company
                    )
                    if fpos:
                        taxes = fpos.map_tax(taxes)

                if taxes:
                    res = taxes.compute_all(
                        price,
                        currency=currency,
                        quantity=qty,
                        product=line.product_id,
                        partner=order.partner_id,
                    )
                    amount_untaxed += res['total_excluded']
                    amount_tax += res['total_included'] - res['total_excluded']
                else:
                    amount_untaxed += qty * price

            order.x_total_m2 = total_m2
            order.x_amount_total = amount_untaxed
            order.x_amount_tax = amount_tax
            order.x_amount_total_taxed = amount_untaxed + amount_tax

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

    def _assert_material_lines_have_placas(self):
        """
        Bloquea confirmación si una línea de material no tiene placas.
        Exenta servicios y líneas backorder (sin lote pero con cantidad y precio
        capturados manualmente como material por pedido).
        """
        for order in self:
            empty = []

            for line in order.line_ids:
                if not line.product_id or line.product_id.type == 'service':
                    continue

                has_lots = bool(line.lot_ids or line.lot_id or line.quant_id)
                if has_lots:
                    continue

                # Backorder legítimo: sin lote/quant, pero con cantidad capturada.
                is_backorder = (
                    (line.cantidad_m2 or 0.0) > 0
                    and (line.precio_unitario or 0.0) >= 0
                    and not line.quant_id
                    and not line.lot_id
                )

                if not is_backorder:
                    empty.append(line.product_id.display_name)

            if empty:
                raise UserError(
                    "Las siguientes líneas no tienen placas seleccionadas y no son "
                    "material por pedido:\n• "
                    + "\n• ".join(empty)
                    + "\n\nAsigna placas con el selector o elimina la línea antes de confirmar."
                )

    def _get_manual_price_violations(self):
        """
        Devuelve líneas de apartado manual que requieren autorización.

        Política comercial (3 roles):
        - Vendedor regular: solo ve Precios 1 y 2. Requiere autorización si el precio
          final queda por debajo del Precio 2. Si por vista heredada llega a usar un
          selector 3/4/5, también cae en autorización.
        - Vendedor mayorista: ve Precios 1..5. Requiere autorización solo si el precio
          queda por debajo del Precio 4.
        - Autorizador: ve Precios 1..5. Requiere autorización solo si el precio
          queda por debajo del Precio 5 (precio mínimo absoluto).
        - Servicios: no participan en la escalera ni en autorización de precio.
        """
        self.ensure_one()

        violations = []
        Product = self.env['product.template']
        role = Product._get_user_price_role()
        threshold_level = Product._get_user_threshold_level()
        threshold_label_map = {
            'medium': 'Precio 2',
            'minimum': 'Precio 3',
            'level_4': 'Precio 4',
            'level_5': 'Precio 5',
        }
        threshold_label = threshold_label_map.get(threshold_level, threshold_level)

        for line in self.line_ids:
            if not line.product_id or line.product_id.type == 'service':
                continue

            currency_code = line._get_currency_code() if hasattr(line, '_get_currency_code') else (
                self.currency_id.name if self.currency_id else 'USD'
            )
            tmpl = line.product_id.product_tmpl_id

            medium_price = Product._get_price_level_value(tmpl, 'medium', currency_code)
            minimum_price = Product._get_price_level_value(tmpl, 'minimum', currency_code)
            level_4_price = Product._get_price_level_value(tmpl, 'level_4', currency_code)
            level_5_price = Product._get_price_level_value(tmpl, 'level_5', currency_code)
            threshold = Product._get_price_level_value(tmpl, threshold_level, currency_code)

            requested_price = float(line.precio_unitario or 0.0)
            selector = line.x_price_selector or 'custom'
            reason = False

            # Vendedor regular: no debe usar selector 3/4/5 directamente.
            if role == 'seller' and selector in ('minimum', 'level_4', 'level_5'):
                reason = (
                    f"selector {selector} requiere autorización para vendedor regular "
                    f"(umbral {threshold_label}: {threshold:.2f})"
                )

            if not reason and threshold > 0 and requested_price < (threshold - 0.01):
                if selector == 'custom':
                    reason = (
                        f"Personalizado {requested_price:.2f} menor al "
                        f"{threshold_label} {threshold:.2f}"
                    )
                else:
                    reason = (
                        f"precio {requested_price:.2f} menor al {threshold_label} "
                        f"{threshold:.2f}"
                    )

            if reason:
                violations.append({
                    'line': line,
                    'reason': reason,
                    'requested_price': requested_price,
                    'medium_price': medium_price,
                    'minimum_price': minimum_price,
                    'level_4_price': level_4_price,
                    'level_5_price': level_5_price,
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

        Product = self.env['product.template']
        for pid_str, group in product_groups.items():
            product = self.env['product.product'].browse(int(pid_str))
            tmpl = product.product_tmpl_id

            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': int(pid_str),
                'quantity': group['total_quantity'],
                'lot_count': len(group['lots']),
                'requested_price': product_prices[pid_str],
                'authorized_price': product_prices[pid_str],
                'medium_price': Product._get_price_level_value(tmpl, 'medium', currency_code),
                'minimum_price': Product._get_price_level_value(tmpl, 'minimum', currency_code),
                'level_4_price': Product._get_price_level_value(tmpl, 'level_4', currency_code),
                'level_5_price': Product._get_price_level_value(tmpl, 'level_5', currency_code),
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

    # -------------------------------------------------------------------------
    # Reserva → Orden de venta: sincronizar selección para stone_select
    # -------------------------------------------------------------------------

    def _stone_get_hold_lines_for_sale_sync(self):
        self.ensure_one()

        lines = self.env['stock.lot.hold.order.line']

        if 'line_ids' in self._fields:
            lines |= self.line_ids

        if 'hold_line_ids' in self._fields:
            lines |= self.hold_line_ids

        return lines.exists()

    def _stone_get_line_lots_for_sale_sync(self, line):
        lots = self.env['stock.lot']

        if 'lot_ids' in line._fields and line.lot_ids:
            lots |= line.lot_ids

        if 'lot_id' in line._fields and line.lot_id:
            lots |= line.lot_id

        if 'quant_id' in line._fields and line.quant_id and line.quant_id.lot_id:
            lots |= line.quant_id.lot_id

        return lots.exists()

    def _stone_get_line_quants_for_sale_sync(self, line, lots):
        Quant = self.env['stock.quant']
        quants = Quant.browse()

        if 'quant_id' in line._fields and line.quant_id:
            quants |= line.quant_id

        if line.product_id and lots:
            domain = [
                ('product_id', '=', line.product_id.id),
                ('lot_id', 'in', lots.ids),
                ('location_id.usage', '=', 'internal'),
                ('quantity', '>', 0),
            ]

            # Primero busca quants que todavía estén ligados a esta reserva.
            if 'x_hold_activo_id' in Quant._fields:
                held_quants = Quant.search(
                    domain + [('x_hold_activo_id', '=', self.id)],
                    order='lot_id, id',
                )
                quants |= held_quants

            # Fallback: si el método base libera el hold antes de terminar,
            # recupera los quants por lote/producto.
            all_quants = Quant.search(domain, order='lot_id, id')
            quants |= all_quants

        return quants.exists()

    def _stone_prepare_sale_sync_payload_from_hold(self):
        """
        Captura lotes/quants ANTES de convertir la reserva.

        Esto es necesario porque el método base de conversión puede liberar
        el apartado. Si esperamos hasta después del super(), ya no siempre se
        puede distinguir qué quants pertenecían a la reserva original.
        """
        self.ensure_one()

        payload_by_product = defaultdict(lambda: {
            'product_id': False,
            'lot_ids': set(),
            'quant_ids': set(),
            'breakdown': {},
        })

        for line in self._stone_get_hold_lines_for_sale_sync():
            if not line.product_id or line.product_id.type == 'service':
                continue

            lots = self._stone_get_line_lots_for_sale_sync(line)
            if not lots:
                continue

            quants = self._stone_get_line_quants_for_sale_sync(line, lots)
            product_id = line.product_id.id

            data = payload_by_product[product_id]
            data['product_id'] = product_id
            data['lot_ids'].update(lots.ids)

            if quants:
                data['quant_ids'].update(quants.ids)
                data['lot_ids'].update(quants.mapped('lot_id').ids)

            # Para formatos/piezas, conservar cantidad seleccionada.
            # stone_select soporta breakdown por lot_id y algunos flujos viejos por quant_id.
            for lot in lots:
                tipo = str(getattr(lot, 'x_tipo', '') or 'placa').lower()
                if tipo not in ('formato', 'pieza'):
                    continue

                qty = 0.0

                if len(lots) == 1 and 'cantidad_m2' in line._fields:
                    qty = float(line.cantidad_m2 or 0.0)

                if qty <= 0 and quants:
                    lot_quants = quants.filtered(lambda q: q.lot_id.id == lot.id)
                    qty = sum(lot_quants.mapped('quantity')) if lot_quants else 0.0

                if qty > 0:
                    data['breakdown'][str(lot.id)] = qty

                    for quant in quants.filtered(lambda q: q.lot_id.id == lot.id):
                        data['breakdown'][str(quant.id)] = qty

        return {
            product_id: {
                'product_id': values['product_id'],
                'lot_ids': list(values['lot_ids']),
                'quant_ids': list(values['quant_ids']),
                'breakdown': values['breakdown'],
            }
            for product_id, values in payload_by_product.items()
            if values['lot_ids']
        }

    def _stone_resolve_sale_order_from_convert_result(self, result=None):
        self.ensure_one()

        sale_order = self.env['sale.order']

        if 'sale_order_id' in self._fields and self.sale_order_id:
            sale_order = self.sale_order_id

        if not sale_order and isinstance(result, dict):
            if result.get('res_model') == 'sale.order' and result.get('res_id'):
                sale_order = self.env['sale.order'].browse(result['res_id'])

        return sale_order.exists()

    def _stone_apply_hold_payload_to_sale_order(self, sale_order, payload_by_product):
        self.ensure_one()

        if not sale_order or not payload_by_product:
            return

        for product_id, payload in payload_by_product.items():
            sale_lines = sale_order.order_line.filtered(
                lambda l:
                    not l.display_type
                    and l.product_id.id == product_id
            )

            if not sale_lines:
                _logger.warning(
                    "[HOLD→STONE] No se encontró línea SO para producto_id=%s en %s",
                    product_id,
                    sale_order.name,
                )
                continue

            target_line = sale_lines.filtered(
                lambda l:
                    ('lot_ids' not in l._fields or not l.lot_ids)
                    and ('x_selected_lots' not in l._fields or not l.x_selected_lots)
            )[:1] or sale_lines[:1]

            vals = {}

            # x_selected_lots puede escribirse aun si la SO queda como cotización.
            # Después, action_confirm de sale.order lo convierte a lot_ids.
            if 'x_selected_lots' in target_line._fields and payload.get('quant_ids'):
                vals['x_selected_lots'] = [(6, 0, payload['quant_ids'])]

            # lot_ids solo se escribe si la SO ya está confirmada.
            # sale_stone_selection bloquea selección de lotes en cotización.
            if sale_order.state in ('sale', 'done'):
                if 'lot_ids' in target_line._fields and payload.get('lot_ids'):
                    vals['lot_ids'] = [(6, 0, payload['lot_ids'])]

                if 'x_lot_breakdown_json' in target_line._fields and payload.get('breakdown'):
                    vals['x_lot_breakdown_json'] = payload['breakdown']

            if vals:
                target_line.sudo().write(vals)

                _logger.info(
                    "[HOLD→STONE] SO %s línea %s sincronizada: lots=%s quants=%s",
                    sale_order.name,
                    target_line.id,
                    len(payload.get('lot_ids') or []),
                    len(payload.get('quant_ids') or []),
                )

        if sale_order.state in ('sale', 'done') and hasattr(sale_order, '_sync_lot_ids_from_selected_lots'):
            sale_order.sudo()._sync_lot_ids_from_selected_lots()

    @staticmethod
    def _hold_line_is_backorder(line):
        """
        Material por pedir: producto físico, sin lote/quant, pero con cantidad
        capturada. No reserva stock, así que no debe pasar por la validación
        de placas del modelo base.
        """
        if not line.product_id or line.product_id.type == 'service':
            return False

        if line.lot_ids or line.lot_id or line.quant_id:
            return False

        return (line.cantidad_m2 or 0.0) > 0

    @api.model
    def _snapshot_hold_line_vals(self, line):
        """
        Copia genérica de todos los campos almacenables y escribibles de la
        línea (sin conocer el esquema del modelo base), para poder recrearla
        tras la confirmación.
        """
        ignore = ('id', 'create_uid', 'create_date', 'write_uid', 'write_date')
        vals = {}

        for name, field in line._fields.items():
            if name in ignore:
                continue
            if not field.store or field.compute or field.related:
                continue

            value = line[name]

            if field.type == 'many2one':
                vals[name] = value.id or False
            elif field.type in ('one2many', 'many2many'):
                vals[name] = [(6, 0, value.ids)]
            else:
                vals[name] = value

        # cantidad_m2 es un campo computed-store (definido en el módulo base),
        # por lo que el loop genérico lo omite. Para el material adicional
        # (línea sin placas) es la cantidad capturada manualmente y DEBE
        # preservarse al recrear la línea tras desprenderla en la confirmación;
        # de lo contrario el material adicional nace en 0 m² en el hold mixto.
        if 'cantidad_m2' in line._fields:
            vals['cantidad_m2'] = line.cantidad_m2

        return vals

    def action_confirm(self):
        self._sync_manual_defaults_and_lines()
        self._assert_material_lines_have_placas()

        for order in self:
            action = order._request_manual_hold_authorization_if_needed()
            if action:
                return action

        HoldLine = self.env['stock.lot.hold.order.line']
        detached_vals = {}

        # 1. Sacar líneas backorder para que el base no las valide ni reserve.
        for order in self:
            backorder_lines = order.line_ids.filtered(self._hold_line_is_backorder)
            if not backorder_lines:
                continue

            if len(backorder_lines) == len(order.line_ids):
                # Apartado 100% por pedir: no hay nada físico que reservar.
                # No se desprende para que el base no confirme un apartado vacío.
                continue

            detached_vals[order.id] = [
                self._snapshot_hold_line_vals(line) for line in backorder_lines
            ]
            backorder_lines.with_context(skip_hold_order_sync=True).unlink()

        # 2. Confirmar (el base solo ve líneas físicas con placas).
        res = super().action_confirm()

        # 3. Reinsertar las líneas backorder en el apartado ya confirmado.
        for order in self:
            vals_list = detached_vals.get(order.id)
            if not vals_list:
                continue

            for vals in vals_list:
                vals['order_id'] = order.id

            HoldLine.with_context(
                skip_hold_order_sync=True,
                skip_hold_line_quantity_sync=True,
                skip_hold_line_price_sync=True,
            ).create(vals_list)

        return res

    def action_convert_to_sale_order(self):
        """
        Corrige Reserva → SO para que stone_select muestre las placas reservadas.

        Flujo:
        1. Captura lotes/quants de la reserva antes del super().
        2. Ejecuta la conversión original.
        3. Localiza la SO creada.
        4. Copia quants a x_selected_lots.
        5. Si la SO ya quedó confirmada, también copia lotes a lot_ids.
        """
        payload_by_order = {
            order.id: order._stone_prepare_sale_sync_payload_from_hold()
            for order in self
        }

        result = super().action_convert_to_sale_order()

        for order in self:
            order.invalidate_recordset()

            sale_order = order._stone_resolve_sale_order_from_convert_result(result)
            payload = payload_by_order.get(order.id) or {}

            if not sale_order:
                _logger.warning(
                    "[HOLD→STONE] Reserva %s convertida, pero no se pudo resolver sale_order_id.",
                    order.name,
                )
                continue

            order._stone_apply_hold_payload_to_sale_order(sale_order, payload)

        return result

    def action_renew(self):
        """Revivir (renovar) el apartado con control por rol.

        - Autorizador de precios (group_price_authorizer): sin límite.
        - Vendedor (normal o mayorista): solo una vez. Después debe crear
          un apartado nuevo desde cero.

        La validación es server-side (no solo ocultar el botón) para que el
        límite no se pueda saltar desde otra vista o por RPC.
        """
        is_authorizer = self.env.user.has_group(
            'inventory_shopping_cart.group_price_authorizer'
        )
        if not is_authorizer:
            for order in self:
                if order.x_renew_count >= 1:
                    raise UserError(
                        'Solo puede revivir este apartado una vez. '
                        'Para volver a apartar este material debe crear un '
                        'apartado nuevo desde cero.'
                    )

        res = super().action_renew()

        # super() ya validó el estado y renovó los holds; contamos la renovación.
        for order in self:
            order.x_renew_count += 1

        return res


class StockLotHoldOrderLine(models.Model):
    _inherit = 'stock.lot.hold.order.line'

    x_price_selector = fields.Selection([
        ('high', 'N1'),
        ('medium', 'N2'),
        ('minimum', 'N3'),
        ('level_4', 'N4'),
        ('level_5', 'N5'),
        ('custom', 'Personalizado'),
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

    x_price_4_value = fields.Float(
        string='Monto Precio 4',
        compute='_compute_price_level_values',
        digits='Product Price',
    )

    x_price_5_value = fields.Float(
        string='Monto Precio 5',
        compute='_compute_price_level_values',
        digits='Product Price',
    )

    x_price_level_currency = fields.Char(
        string='Moneda Nivel Precio',
        compute='_compute_price_level_values',
    )

    x_can_use_custom_price = fields.Boolean(
        string='Puede usar Personalizado',
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

    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unidad de Medida',
        related='product_id.uom_id',
        readonly=True,
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

    x_tax_amount = fields.Monetary(
        string='Impuestos',
        compute='_compute_x_tax_amount',
        store=True,
        currency_field='currency_id',
        help='Impuesto de la línea según los impuestos de venta del producto '
             '(mapeados por la posición fiscal del cliente).',
    )

    @api.depends(
        'product_id',
        'product_id.taxes_id',
        'cantidad_m2',
        'precio_unitario',
        'currency_id',
        'order_id.partner_id',
        'order_id.partner_id.property_account_position_id',
        'order_id.company_id',
    )
    def _compute_x_tax_amount(self):
        for line in self:
            qty = line.cantidad_m2 or 0.0
            price = line.precio_unitario or 0.0
            company = line.order_id.company_id or self.env.company
            currency = line.currency_id or company.currency_id

            taxes = self.env['account.tax']
            if line.product_id:
                taxes = line.product_id.taxes_id.filtered(
                    lambda t: t.company_id == company
                )
                fpos = line.order_id.partner_id.property_account_position_id
                if fpos:
                    taxes = fpos.map_tax(taxes)

            if taxes and qty and price:
                res = taxes.compute_all(
                    price,
                    currency=currency,
                    quantity=qty,
                    product=line.product_id,
                    partner=line.order_id.partner_id,
                )
                line.x_tax_amount = res['total_included'] - res['total_excluded']
            else:
                line.x_tax_amount = 0.0

    @api.depends_context('uid')
    def _compute_x_price_permission_flags(self):
        """
        El Personalizado debe estar disponible desde el formulario manual,
        igual que en el carrito. La autorización se decide al confirmar.

        Los Precios 3, 4 y 5 se exponen para vendedores mayoristas y autorizadores.
        El vendedor regular solo puede usar Precio 1 y Precio 2.
        """
        role = self.env['product.template']._get_user_price_role()
        can_use_mayorista = role in ('authorizer', 'mayorista')
        for line in self:
            line.x_can_use_custom_price = True
            line.x_can_use_minimum_price = can_use_mayorista

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
                line.x_price_4_value = tmpl.x_price_mxn_4
                line.x_price_5_value = tmpl.x_price_mxn_5
            elif tmpl:
                line.x_price_1_value = tmpl.x_price_usd_1
                line.x_price_2_value = tmpl.x_price_usd_2
                line.x_price_3_value = tmpl.x_price_usd_3
                line.x_price_4_value = tmpl.x_price_usd_4
                line.x_price_5_value = tmpl.x_price_usd_5
            else:
                line.x_price_1_value = 0.0
                line.x_price_2_value = 0.0
                line.x_price_3_value = 0.0
                line.x_price_4_value = 0.0
                line.x_price_5_value = 0.0

            line.x_price_level_currency = currency_code

    @api.depends('cantidad_m2', 'precio_unitario')
    def _compute_x_subtotal(self):
        for line in self:
            line.x_subtotal = (line.cantidad_m2 or 0.0) * (line.precio_unitario or 0.0)

    @api.depends('lot_ids', 'product_id')
    def _compute_cantidad_m2(self):
        """
        Sobrescribe el cómputo del módulo base.

        El base, para una línea de producto físico SIN placas, forzaba
        `cantidad_m2 = 0.0`. Pero ese es exactamente el caso del "material
        adicional" (material por pedir, capturado manualmente desde el carrito):
        debe CONSERVAR la cantidad que indicó el usuario (p. ej. 100 m²), no
        reiniciarla a cero.

        - Con placas: se recalcula desde el inventario (igual que el base).
        - Servicio: 1.0 por defecto si está vacío.
        - Material adicional (físico sin placas): se conserva lo capturado.
        """
        for line in self:
            if line.lot_ids:
                total = 0.0
                for lot in line.lot_ids:
                    quant = self.env['stock.quant'].search([
                        ('lot_id', '=', lot.id),
                        ('quantity', '>', 0),
                        ('location_id.usage', '=', 'internal'),
                    ], limit=1)
                    total += quant.quantity if quant else 0.0
                line.cantidad_m2 = total
            elif line.product_id and line.product_id.type == 'service':
                if not line.cantidad_m2:
                    line.cantidad_m2 = 1.0
            else:
                # Material adicional / backorder: conservar la cantidad
                # capturada manualmente; solo poner 0 si aún no hay valor.
                if not line.cantidad_m2:
                    line.cantidad_m2 = 0.0

    @api.model
    def _selector_from_price(self, product_id, currency_code, price):
        product = self.env['product.product'].browse(int(product_id))
        if not product.exists():
            return 'custom'

        Product = self.env['product.template']
        tmpl = product.product_tmpl_id

        price = float(price or 0.0)

        for level in ('high', 'medium', 'minimum', 'level_4', 'level_5'):
            level_price = Product._get_price_level_value(tmpl, level, currency_code)
            if level_price and abs(price - level_price) <= 0.01:
                return level

        return 'custom'

    def _get_price_from_selector(self):
        self.ensure_one()

        if not self.product_id:
            return 0.0

        currency_code = self._get_currency_code()
        tmpl = self.product_id.product_tmpl_id

        if self.x_price_selector in ('high', 'medium', 'minimum', 'level_4', 'level_5'):
            return self.env['product.template']._get_price_level_value(
                tmpl, self.x_price_selector, currency_code,
            )

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

    @api.model
    def get_available_stone_quants(self, product_id, hold_order_id=False,
                                   lot_name=False, location_name=False, limit=500):
        """Placas seleccionables para el selector del apartado.

        Excluye exactamente lo que `_assert_quants_can_be_used` rechazaría al
        convertir la reserva en SO, para no ofrecer placas ya comprometidas:
        - Lotes con reserva nativa activa en otra SO / orden de entrega.
        - Lotes en un hold activo distinto al que se está editando.

        Devuelve la misma forma que el `search_read` anterior (lot_id y
        location_id como [id, nombre]) para no romper el render del widget.
        """
        if not product_id:
            return []

        Quant = self.env['stock.quant'].sudo()
        SaleOrder = self.env['sale.order']

        domain = [
            ('product_id', '=', product_id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ]
        if lot_name:
            domain.append(('lot_id.name', 'ilike', lot_name))
        if location_name:
            domain.append(('location_id.complete_name', 'ilike', location_name))

        quants = Quant.search(domain, limit=limit, order='lot_id')

        available = Quant.browse()
        for quant in quants:
            if not quant.lot_id:
                continue

            # Hold activo de OTRA reserva: la placa ya está apartada.
            if getattr(quant, 'x_tiene_hold', False) and quant.x_hold_activo_id:
                if not hold_order_id or quant.x_hold_activo_id.id != hold_order_id:
                    continue

            # Reserva nativa activa en otra SO / entrega. Solo puede existir si el
            # quant tiene cantidad reservada, así evitamos una búsqueda por placa libre.
            if quant.reserved_quantity > 0 and SaleOrder._get_native_reservation_blockers(quant):
                continue

            available |= quant

        optional_fields = [
            'x_bloque', 'x_atado', 'x_alto', 'x_ancho', 'x_grosor', 'x_tipo', 'x_color',
        ]
        read_fields = ['id', 'lot_id', 'location_id', 'quantity', 'reserved_quantity']
        read_fields += [f for f in optional_fields if f in Quant._fields]

        return available.read(read_fields)

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
                