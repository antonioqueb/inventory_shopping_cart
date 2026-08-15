# -*- coding: utf-8 -*-
# models/sale_order.py

import math
import logging
import re

from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.stock_lot_dimensions.models.utils.picking_cleaner import PickingLotCleaner
except ImportError:
    PickingLotCleaner = None


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ------------------------------------------------------------------
    # DESCUENTOS: CLAMP HASTA AUTORIZAR (mismo patrón que precios mínimos)
    # ------------------------------------------------------------------
    # El descuento capturado que dispara autorización NO SE APLICA: se
    # guarda aquí como solicitado, la solicitud se lanza sola y el
    # Autorizador decide. Al aprobar, pasa a 'discount'; al rechazar, se
    # descarta. Cambiarlo después de aprobado vuelve a requerir auth.
    x_requested_discount = fields.Float(
        string='Desc. solicitado (%)',
        copy=False, readonly=True,
        help='Descuento capturado pendiente de autorización: NO se aplica '
             'a la línea hasta que un Autorizador de Precios Mínimos lo '
             'apruebe. Al rechazar, se descarta.',
    )

    def _som_split_discount_clamp(self, new_disc):
        """Subconjunto de líneas cuyo NUEVO descuento requiere autorización
        (el monto prospectivo de descuento de la orden cruza el umbral y
        supera lo ya autorizado). Autorizadores y flujos administrativos
        (excedente/cierre corto de Torre de Control) no se topan."""
        clamped = self.browse()
        if (
            self.env.context.get('som_discount_auth_apply')
            or self.env.context.get('skip_tc_qty_manual_reset')
            or self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        ):
            return clamped
        # ACUMULATIVO por orden: en una escritura en lote (descuento global
        # en % sobre todas las líneas) ninguna línea cruza el umbral sola,
        # pero la suma sí — lo que se va a aplicar cuenta como base de las
        # siguientes líneas del mismo write.
        running = {}
        for line in self:
            order = line.order_id
            if line.display_type or not line.product_id or not order:
                continue
            # Bajar (o igualar) el descuento se aplica directo: nunca
            # aumenta el monto descontado.
            if new_disc <= (line.discount or 0.0) + 0.0001:
                continue
            delta = (line.price_unit or 0.0) * (line.product_uom_qty or 0.0) \
                * (new_disc - (line.discount or 0.0)) / 100.0
            delta_mxn = order._discount_amount_to_mxn(delta)
            base = (order.x_discount_amount_mxn or 0.0) \
                + running.get(order.id, 0.0)
            prospective = base + delta_mxn
            if prospective >= order._get_discount_auth_threshold_mxn() \
                    and prospective > (order.x_discount_authorized_amount or 0.0) + 0.01:
                clamped |= line
            else:
                running[order.id] = running.get(order.id, 0.0) + delta_mxn
        return clamped

    # ------------------------------------------------------------------
    # IVA 16% OBLIGATORIO EN TODA VENTA (productos Y servicios)
    # ------------------------------------------------------------------
    # Toda línea con producto lleva IVA 16% SIEMPRE. Quitarlo requiere que
    # la orden tenga aprobada la exención (x_iva_exempt_state). Se fuerza
    # silenciosamente en create/write: si alguien lo quita, se re-agrega.

    def _som_get_service_iva_tax(self, company):
        return self.env['account.tax'].sudo().search([
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 16),
            ('company_id', '=', (company or self.env.company).id),
        ], limit=1)

    def _som_line_has_iva16(self):
        self.ensure_one()
        return any(
            t.type_tax_use == 'sale'
            and t.amount_type == 'percent'
            and t.amount == 16
            for t in self.tax_ids
        )

    def _som_force_service_iva(self):
        for line in self:
            if (
                not line.product_id
                or line.display_type
                or line.state in ('done', 'cancel')
                or line.order_id.x_iva_exempt_state == 'approved'
            ):
                continue

            ops = []

            # El IVA 0% de venta (default de algunos productos) NO debe
            # convivir con el 16 forzado: se retira siempre que la orden
            # no tenga exención aprobada.
            zero_taxes = line.tax_ids.filtered(
                lambda t: t.type_tax_use == 'sale'
                and t.amount_type == 'percent'
                and not t.amount)
            ops.extend((3, t.id) for t in zero_taxes)

            if not line._som_line_has_iva16():
                tax = line._som_get_service_iva_tax(line.company_id)
                if tax:
                    ops.append((4, tax.id))

            if ops:
                line.with_context(som_skip_iva_force=True).tax_ids = ops

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get('som_skip_iva_force'):
            lines._som_force_service_iva()

        # CLAMP de descuentos también en líneas NUEVAS con descuento: si el
        # monto de descuento de la orden ya cruza el umbral, el descuento de
        # la línea se retira y queda como SOLICITADO.
        if not (
            self.env.context.get('som_discount_auth_apply')
            or self.env.context.get('skip_tc_qty_manual_reset')
            or self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        ):
            clamped = lines.browse()
            for line in lines:
                if line.display_type or not line.product_id \
                        or (line.discount or 0.0) <= 0 or not line.order_id:
                    continue
                order = line.order_id
                amount = order.x_discount_amount_mxn or 0.0
                if amount >= order._get_discount_auth_threshold_mxn() \
                        and amount > (order.x_discount_authorized_amount or 0.0) + 0.01:
                    clamped |= line
            if clamped:
                for line in clamped:
                    line.with_context(
                        som_discount_clamp_done=True, som_skip_iva_force=True,
                    ).write({
                        'x_requested_discount': line.discount,
                        'discount': 0.0,
                    })
                clamped.order_id._som_discount_auth_auto_request()

        return lines

    def write(self, vals):
        # CLAMP de descuentos (patrón precios mínimos): un descuento que
        # dispara autorización NO se aplica — queda solicitado y la
        # solicitud se lanza sola. Aplica igual si el descuento entra por
        # la columna de la línea o por el botón de descuento global (el
        # modo porcentaje escribe 'discount' en cada línea).
        if vals.get('discount') and not self.env.context.get('som_discount_clamp_done'):
            try:
                new_disc = float(vals['discount'])
            except (TypeError, ValueError):
                new_disc = 0.0
            if new_disc > 0:
                clamped = self._som_split_discount_clamp(new_disc)
                if clamped:
                    rest = self - clamped
                    res = True
                    if rest:
                        res = rest.with_context(som_discount_clamp_done=True).write(vals)
                    clamp_vals = dict(vals)
                    clamp_vals.pop('discount')
                    clamp_vals['x_requested_discount'] = new_disc
                    clamped.with_context(som_discount_clamp_done=True).write(clamp_vals)
                    clamped.order_id._som_discount_auth_auto_request()
                    return res

        # Vigilancia del piso autorizado: se detecta el CRUCE (antes bien,
        # después por debajo) para alertar una sola vez.
        floor_watch = None
        if 'price_unit' in vals:
            floor_watch = {
                order.id: bool(order._som_authorized_floor_violations())
                for order in self.order_id
            }

        res = super().write(vals)
        if (
            not self.env.context.get('som_skip_iva_force')
            and ('tax_ids' in vals or 'product_id' in vals)
        ):
            self._som_force_service_iva()

        if floor_watch is not None:
            for order in self.order_id:
                if floor_watch.get(order.id):
                    continue
                violations = order._som_authorized_floor_violations()
                if violations:
                    order._som_alert_floor_violation(violations)

        # ESPEJO carrito ⇄ selector de placas en órdenes confirmadas.
        # x_selected_lots era una TERCERA copia de la selección que se
        # congelaba con lo elegido en el carrito: al quitar material desde
        # el selector, el carrito lo conservaba y flujos posteriores
        # (asignación, limpieza de lotes automáticos que exenta lo
        # "seleccionado en carrito") re-reservaban el lote en el picking
        # como fantasma — invisible en el selector e imposible de volver a
        # asignar. Ahora ambas copias se realinean en cada cambio.
        if not self.env.context.get('som_skip_cart_mirror'):
            if 'lot_ids' in vals and 'lot_ids' in self._fields:
                self._som_mirror_stone_to_cart()
            elif 'x_selected_lots' in vals and 'lot_ids' in self._fields:
                self._som_mirror_cart_to_stone()
        return res

    @api.model
    def _som_fix_stone_cart_desync(self):
        """Reparación de órdenes YA existentes (corre en cada -u, idempotente):

        1. Líneas confirmadas con selección: si el picking trae lotes que no
           están en el selector (fantasmas) o le faltan lotes seleccionados,
           se reconstruye con la sync canónica de sale_stone_selection.
        2. Realinea x_selected_lots (carrito) con lot_ids.

        Solo toca movimientos vivos (no done/cancel); lo ya entregado no se
        modifica. Tras la primera pasada los espejos mantienen todo igual,
        así que las corridas siguientes no encuentran nada.
        """
        if 'lot_ids' not in self._fields:
            return

        # 0. ADOPCIÓN (caso orden 91): línea confirmada SIN selección pero
        #    cuya ENTREGA sí trae lotes — órdenes previas al espejo donde la
        #    copia entrega→venta nunca corrió. Ahí la entrega es la verdad
        #    y se propaga a la orden de venta (lot_ids + breakdown para
        #    formato/pieza); el picking NO se toca.
        adopted = 0
        for line in self.search([
            ('state', 'in', ('sale', 'done')),
            ('lot_ids', '=', False),
        ]):
            if line.display_type or not line.product_id:
                continue
            mls = line.move_ids.filtered(
                lambda m: m.state != 'cancel'
            ).move_line_ids.filtered(lambda ml: ml.lot_id)
            if not mls:
                continue
            qty_field = ('quantity' if 'quantity' in mls._fields
                         else 'qty_done')
            # Por lote, la mayor cantidad registrada en UN solo picking
            # (en multi-paso cada paso repite la cantidad).
            by_lot_pick = {}
            for ml in mls:
                key = (ml.lot_id.id, ml.picking_id.id or 0)
                by_lot_pick[key] = by_lot_pick.get(key, 0.0) + float(
                    getattr(ml, qty_field, 0.0) or 0.0)
            qty_by_lot = {}
            for (lot_id, _pick), qty in by_lot_pick.items():
                if qty > qty_by_lot.get(lot_id, 0.0):
                    qty_by_lot[lot_id] = qty
            lot_ids = [k for k, v in qty_by_lot.items() if v > 0]
            if not lot_ids:
                continue
            breakdown = {}
            for lot in self.env['stock.lot'].browse(lot_ids):
                tipo = str(getattr(lot, 'x_tipo', '') or 'placa').lower()
                if tipo in ('formato', 'pieza'):
                    breakdown[str(lot.id)] = qty_by_lot.get(lot.id, 0.0)
            _logger.warning(
                "[CART MIRROR FIX] Línea %s (%s): adoptando %s lote(s) "
                "de la ENTREGA hacia la orden de venta.",
                line.id, line.order_id.name, len(lot_ids))
            vals = {'lot_ids': [(6, 0, lot_ids)]}
            if breakdown:
                vals['x_lot_breakdown_json'] = breakdown
            # skip_stone_sync_picking: la entrega es la fuente, no se
            # reconstruye. El espejo al carrito sí corre en el write.
            line.with_context(
                skip_stone_sync_picking=True,
                skip_hold_validation=True,
            ).write(vals)
            adopted += 1

        lines = self.search([
            ('state', 'in', ('sale', 'done')),
            ('lot_ids', '!=', False),
        ])
        fixed_pick = fixed_cart = 0
        for line in lines:
            live_moves = line.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel'))
            if live_moves:
                picking_lots = set(
                    live_moves.move_line_ids.mapped('lot_id').ids)
                if picking_lots != set(line.lot_ids.ids):
                    _logger.warning(
                        "[CART MIRROR FIX] Línea %s (%s): picking %s ≠ "
                        "selector %s — reconstruyendo.",
                        line.id, line.order_id.name,
                        sorted(picking_lots), sorted(line.lot_ids.ids))
                    if hasattr(line, '_sync_lots_to_picking_moves'):
                        line.with_context(
                            skip_hold_validation=True,
                        )._sync_lots_to_picking_moves()
                        fixed_pick += 1
            if (set(line.x_selected_lots.mapped('lot_id').ids)
                    != set(line.lot_ids.ids)):
                line._som_mirror_stone_to_cart()
                fixed_cart += 1
        _logger.info(
            "[CART MIRROR FIX] Reparación terminada: %s líneas adoptaron "
            "la selección de su entrega, %s pickings reconstruidos, %s "
            "carritos realineados (de %s líneas con selección).",
            adopted, fixed_pick, fixed_cart, len(lines))

    def _som_mirror_stone_to_cart(self):
        """lot_ids (selector de placas) manda en órdenes confirmadas:
        realinea x_selected_lots para que el carrito jamás retenga material
        ya quitado ni le falte material agregado."""
        for line in self:
            if line.state not in ('sale', 'done'):
                continue
            target_lots = line.lot_ids
            current = line.x_selected_lots
            if set(current.mapped('lot_id').ids) == set(target_lots.ids):
                continue
            keep = current.filtered(
                lambda q: q.lot_id and q.lot_id in target_lots)
            missing = target_lots - keep.mapped('lot_id')
            add = self.env['stock.quant']
            for lot in missing:
                add |= self.env['stock.quant'].search([
                    ('lot_id', '=', lot.id),
                    ('location_id.usage', '=', 'internal'),
                    ('quantity', '>', 0),
                ], limit=1)
            _logger.info(
                "[CART MIRROR] Línea %s: x_selected_lots realineado a "
                "lot_ids (%s lotes).", line.id, len(target_lots))
            mirror_vals = {'x_selected_lots': [(6, 0, (keep | add).ids)]}
            # Si el realineo SUSTITUYE un quant, las llaves de quant del
            # desglose que apuntaban al quant saliente se re-keyean a su
            # LOTE — sin esto la parcialidad dejaba de resolverse y el lote
            # degradaba a "completo" en reportes y syncs.
            bd = line.x_lot_breakdown_json or {}
            if bd:
                kept_quants = {str(q.id) for q in (keep | add)}
                old_map = {
                    str(q.id): q.lot_id.id for q in current if q.lot_id}
                rekeyed = {}
                changed = False
                for k, v in bd.items():
                    ks = str(k)
                    if (ks.isdigit() and ks not in kept_quants
                            and ks in old_map):
                        rekeyed.setdefault(str(old_map[ks]), v)
                        changed = True
                    else:
                        rekeyed[ks] = v
                if changed:
                    mirror_vals['x_lot_breakdown_json'] = rekeyed
            line.with_context(som_skip_cart_mirror=True).write(mirror_vals)

    def _som_mirror_cart_to_stone(self):
        """Cambios de x_selected_lots en una línea confirmada se propagan a
        lot_ids: el write de lot_ids dispara la sincronización existente
        hacia el picking (sale_stone_selection), que quita/agrega las move
        lines. Así lo que se borra del carrito se borra de la entrega."""
        for line in self:
            if line.state not in ('sale', 'done'):
                continue
            lot_ids = line.x_selected_lots.mapped('lot_id').ids
            if set(line.lot_ids.ids) == set(lot_ids):
                continue
            # RE-KEY antes de filtrar: el desglose puede venir con llaves de
            # QUANT (flujo de carrito/hold). El filtro viejo solo reconocía
            # llaves de LOTE y BORRABA la parcialidad completa (el lote
            # pasaba a "entero" en visual, ratchet y picking). Cada llave de
            # quant se traduce a su lote antes de decidir qué se conserva.
            quant_to_lot = {
                str(q.id): q.lot_id.id
                for q in line.x_selected_lots if q.lot_id
            }
            breakdown = {}
            for k, v in (line.x_lot_breakdown_json or {}).items():
                key = str(k)
                if not key.isdigit():
                    continue
                if int(key) in lot_ids:
                    breakdown[key] = v
                elif key in quant_to_lot and quant_to_lot[key] in lot_ids:
                    # llave de quant → re-key al lote (sin pisar una llave de
                    # lote ya existente)
                    breakdown.setdefault(str(quant_to_lot[key]), v)
            _logger.info(
                "[CART MIRROR] Línea %s: propagando carrito → selector "
                "(%s lotes) y picking.", line.id, len(lot_ids))
            line.with_context(som_skip_cart_mirror=True).write({
                'lot_ids': [(6, 0, lot_ids)],
                'x_lot_breakdown_json': breakdown or False,
            })

    x_selected_lots = fields.Many2many(
        'stock.quant',
        string='Lotes Seleccionados',
        copy=True,
    )

    x_lot_breakdown_json = fields.Json(
        string='Desglose de Lotes',
        copy=True,
    )

    x_price_selector = fields.Selection([
        ('high', 'N1'),
        ('medium', 'N2'),
        ('minimum', 'N3'),
        ('level_4', 'N4'),
        ('level_5', 'N5'),
        ('custom', 'Personalizado'),
    ], string='Nivel de Precio', default='high',
       help="Seleccione el nivel de precio.")

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
        string='Puede usar Precios 3-5',
        compute='_compute_x_price_permission_flags',
        help="Indica si el usuario puede usar los niveles 3, 4 y 5 (vendedores mayoristas y autorizadores).",
    )

    @api.depends_context('uid')
    def _compute_x_price_permission_flags(self):
        Product = self.env['product.template']
        role = Product._get_user_price_role()
        can_use_mayorista = role in ('authorizer', 'mayorista')
        for line in self:
            line.x_can_use_custom_price = True
            line.x_can_use_minimum_price = can_use_mayorista

    @api.depends('product_id', 'order_id.pricelist_id', 'order_id.pricelist_id.currency_id')
    def _compute_price_level_values(self):
        for line in self:
            currency_name = 'USD'

            if line.order_id.pricelist_id and line.order_id.pricelist_id.currency_id:
                currency_name = line.order_id.pricelist_id.currency_id.name
            elif line.env.context.get('default_pricelist_id'):
                pricelist = line.env['product.pricelist'].browse(line.env.context['default_pricelist_id'])
                if pricelist.exists() and pricelist.currency_id:
                    currency_name = pricelist.currency_id.name

            tmpl = line.product_id.product_tmpl_id if line.product_id else False

            if tmpl and currency_name == 'MXN':
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

            line.x_price_level_currency = currency_name

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
            new_price = self.env['product.template']._get_price_level_value(
                template, line.x_price_selector, currency_name,
            )

            if new_price > 0:
                line.price_unit = new_price


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    partner_invoice_id = fields.Many2one(
        'res.partner',
        required=False,
    )

    partner_shipping_id = fields.Many2one(
        'res.partner',
        required=False,
    )

    x_project_id = fields.Many2one(
        'project.project',
        string='Proyecto',
        help='Proyecto del CLIENTE de esta orden. Un cliente tiene muchos '
             'proyectos; una orden pertenece a uno. Crear un proyecto desde '
             'aquí lo registra a nombre del cliente.',
    )

    @api.onchange('partner_id')
    def _onchange_partner_som_project(self):
        """Relación cliente→proyectos: al cambiar de cliente, un proyecto
        de OTRO cliente no puede quedarse en la orden."""
        for order in self:
            proj = order.x_project_id
            if not proj or not proj.partner_id or not order.partner_id:
                continue
            if proj.partner_id.commercial_partner_id != order.partner_id.commercial_partner_id:
                order.x_project_id = False

    x_architect_id = fields.Many2one(
        'res.partner',
        string='Embajador',
    )

    x_price_authorization_id = fields.Many2one(
        'price.authorization',
        string="Autorización Vinculada",
        copy=False,
        readonly=True,
    )

    x_is_quote_backup = fields.Boolean(
        string="Es Respaldo de Cotización",
        default=False,
        copy=False,
    )

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
        string='Tipo de Cambio',
        digits=(12, 4),
        compute='_compute_exchange_rate',
    )

    x_is_usd = fields.Boolean(
        string='Es USD',
        compute='_compute_is_usd',
    )

    # =========================================================================
    # DIVISA EDITABLE HASTA LA ENTREGA
    # La confirmación NO congela la divisa/TC: mientras no haya entrega
    # validada (ni factura publicada), la lista de precios puede cambiarse
    # (MXN⇄USD) y los precios se remapean. El TC se CONGELA con la primera
    # entrega validada, y queda como registro.
    # =========================================================================
    x_confirm_exchange_rate = fields.Float(
        string='TC al confirmar',
        digits=(12, 4),
        copy=False,
        readonly=True,
        help='TC Banorte vigente al confirmar la orden. Contra el TC '
             'congelado en la entrega mide la ganancia/pérdida cambiaria '
             'operativa de la ventana confirmación→entrega.',
    )
    x_delivery_exchange_rate = fields.Float(
        string='TC congelado en entrega',
        digits=(12, 4),
        copy=False,
        readonly=True,
        help='Tipo de cambio vigente al validar la PRIMERA entrega. A partir '
             'de ahí la divisa de la orden ya no puede cambiarse.',
    )
    x_pricelist_locked = fields.Boolean(
        string='Divisa bloqueada',
        compute='_compute_pricelist_locked',
    )

    @api.depends(
        'state',
        'x_delivery_exchange_rate',
        'picking_ids.state',
        'picking_ids.picking_type_code',
        'invoice_ids.state',
    )
    def _compute_pricelist_locked(self):
        for order in self:
            delivered = any(
                p.picking_type_code == 'outgoing' and p.state == 'done'
                for p in order.picking_ids
            )
            invoiced = any(
                m.move_type == 'out_invoice' and m.state == 'posted'
                for m in order.invoice_ids
            )
            order.x_pricelist_locked = bool(
                order.state == 'cancel'
                or order.x_delivery_exchange_rate
                or delivered
                or invoiced
            )

    def _som_freeze_delivery_rate(self):
        """Congela el TC de la orden al validar su primera entrega."""
        for order in self:
            if order.x_delivery_exchange_rate:
                continue
            rate = order.x_exchange_rate or 0.0
            order.write({'x_delivery_exchange_rate': rate})
            order.message_post(body=Markup(
                f"<p>🔒 <b>Tipo de cambio congelado por entrega</b>: "
                f"{rate:.4f} MXN/USD "
                f"(fuente: {'Banorte' if order.x_exchange_rate_source == 'banorte' else 'DOF'}). "
                f"La divisa de la orden ya no puede cambiarse.</p>"
            ))

    # =========================================================================
    # AUTORIZACIÓN DE DESCUENTOS ALTOS
    # Si el valor del descuento de la orden (en MXN) alcanza el umbral
    # (por defecto 2,000 MXN), la orden queda BLOQUEADA hasta que un
    # "Autorizador de Precios Mínimos" la autorice. Aplica igual al descuento
    # manual por línea y al excedente "no cobrado" (free) desde Transit Allocation.
    # =========================================================================
    x_discount_amount_mxn = fields.Float(
        string="Descuento (MXN)",
        compute='_compute_discount_amount_mxn',
        store=True,
        help="Valor total del descuento de la orden convertido a MXN.",
    )
    x_discount_authorized_amount = fields.Float(
        string="Descuento Autorizado (MXN)",
        default=0.0,
        copy=False,
        readonly=True,
    )
    x_discount_needs_auth = fields.Boolean(
        string="Descuento Requiere Autorización",
        compute='_compute_discount_needs_auth',
        store=True,
    )
    x_discount_auth_requested = fields.Boolean(
        string="Autorización de Descuento Solicitada",
        default=False,
        copy=False,
    )
    x_discount_auth_result = fields.Selection([
        ('approved', 'Aprobado'),
        ('rejected', 'Rechazado'),
    ], string="Resultado de Autorización de Descuento", copy=False)
    x_discount_rejected_amount = fields.Float(
        string="Descuento Evitado (MXN)", default=0.0, copy=False,
        help="Descuento rechazado por el autorizador: margen rescatado.",
    )

    # -------------------------------------------------------------------------
    # GUARDIA CENTRAL CONTRA DOBLE RESERVA DE LOTES / QUANTS
    # -------------------------------------------------------------------------

    def _get_selected_quant_ids_from_products_payload(self, products):
        quant_ids = []

        for product in products or []:
            for quant_id in product.get('selected_lots') or []:
                try:
                    quant_ids.append(int(quant_id))
                except Exception:
                    continue

        return list(dict.fromkeys(quant_ids))

    def _get_selected_quants_from_order(self):
        quants = self.env['stock.quant'].sudo()

        for order in self:
            for line in order.order_line:
                if line.display_type or not line.product_id:
                    continue

                if line.product_id.type not in ['product', 'consu']:
                    continue

                if line.x_selected_lots:
                    quants |= line.x_selected_lots.sudo()

        return quants.exists()

    def _resolve_sale_order_from_pickings(self, pickings):
        sale_order = self.env['sale.order'].sudo()

        if not pickings:
            return sale_order

        if 'sale_id' in pickings._fields:
            sale_order |= pickings.mapped('sale_id').sudo()

        sale_order |= pickings.mapped('move_ids.sale_line_id.order_id').sudo()

        return sale_order.exists()[:1]

    def _get_native_reservation_blockers(self, quant, allowed_order=False, allowed_pickings=False):
        """
        Busca reservas nativas activas del mismo quant lógico.

        No filtra por picking_type_code='outgoing' porque en flujos multi-step
        el compromiso de venta puede vivir en un picking interno, por ejemplo:
        SOM/Existencias -> SOM/Salida.
        """
        StockMoveLine = self.env['stock.move.line'].sudo()

        if not quant or not quant.exists() or not quant.lot_id:
            return StockMoveLine.browse()

        domain = [
            ('product_id', '=', quant.product_id.id),
            ('lot_id', '=', quant.lot_id.id),
            ('location_id', '=', quant.location_id.id),
            ('state', 'in', ['assigned', 'partially_available']),
            ('quantity', '>', 0),
        ]

        if quant.company_id:
            domain.append(('company_id', '=', quant.company_id.id))

        if quant.package_id:
            domain.append(('package_id', '=', quant.package_id.id))
        else:
            domain.append(('package_id', '=', False))

        if quant.owner_id:
            domain.append(('owner_id', '=', quant.owner_id.id))
        else:
            domain.append(('owner_id', '=', False))

        blockers = StockMoveLine.search(domain)

        # Reserva DÉBIL: un traslado interno de carrito/escáner abierto es
        # solo reacomodo de ubicación, nunca un compromiso comercial. Los
        # flujos fuertes ya lo liberan vía
        # stock.picking._release_cart_internal_reservations(); este filtro es
        # el cinturón por si la liberación corrió en otra transacción y la
        # caché aún lo trae. OJO: solo origin 'Carrito - %' — los pickings
        # internos multi-step de una venta (Existencias -> Salida) llevan la
        # SO en origin y SÍ deben bloquear.
        blockers = blockers.filtered(lambda ml: not (
            ml.picking_id
            and ml.picking_id.picking_type_code == 'internal'
            and (ml.picking_id.origin or '').startswith('Carrito - ')
        ))

        if allowed_pickings:
            allowed_picking_ids = set(allowed_pickings.ids)
            blockers = blockers.filtered(lambda ml: ml.picking_id.id not in allowed_picking_ids)

        if allowed_order:
            # Una reserva NO bloquea si pertenece a la cadena logística de la
            # propia orden. El vínculo directo (move.sale_line_id) no basta:
            # los pickings creados por stock_transit_allocation (Asignar /
            # Mandar a pedir — que standard_pack_som enciende por defecto)
            # reservan el lote SIN sale_line_id y solo se ligan a la SO por
            # group_id, sale_id del picking u origin con el nombre de la SO.
            # Sin esta exclusión amplia, la propia orden se auto-bloqueaba con
            # "el lote ya está reservado en otra operación activa".
            order_names = [
                name for name in [allowed_order.name, allowed_order.origin]
                if name
            ]

            def _belongs_to_allowed_order(ml):
                move = ml.move_id
                picking = ml.picking_id

                if move and move.sale_line_id and move.sale_line_id.order_id.id == allowed_order.id:
                    return True

                # Odoo 19: stock.move ya NO tiene group_id (AttributeError);
                # se consulta por nombre de campo tolerando renombres, y
                # también vía el grupo del picking.
                if move:
                    for group_field in ('group_id', 'procure_group_id'):
                        if group_field not in move._fields:
                            continue
                        group = move[group_field]
                        if (
                            group
                            and 'sale_id' in group._fields
                            and group.sale_id
                            and group.sale_id.id == allowed_order.id
                        ):
                            return True
                        break

                if picking and 'group_id' in picking._fields and picking.group_id:
                    group = picking.group_id
                    if (
                        'sale_id' in group._fields
                        and group.sale_id
                        and group.sale_id.id == allowed_order.id
                    ):
                        return True

                if (
                    picking
                    and 'sale_id' in picking._fields
                    and picking.sale_id
                    and picking.sale_id.id == allowed_order.id
                ):
                    return True

                origin = (picking.origin or '') if picking else ''
                if origin and any(name in origin for name in order_names):
                    return True

                return False

            blockers = blockers.filtered(
                lambda ml: not _belongs_to_allowed_order(ml)
            )

        return blockers

    def _format_native_reservation_blockers(self, blockers):
        docs = []

        for ml in blockers:
            picking_name = ml.picking_id.name or 'Sin picking'
            origin = ml.picking_id.origin or ''
            so = ml.move_id.sale_line_id.order_id if ml.move_id and ml.move_id.sale_line_id else False

            if so:
                docs.append(f"{picking_name} / {so.name}")
            elif origin:
                docs.append(f"{picking_name} / {origin}")
            else:
                docs.append(picking_name)

        return ', '.join(sorted(set(docs)))

    def _assert_quants_can_be_used(
        self,
        quants,
        partner_id=False,
        allowed_order=False,
        allowed_pickings=False,
    ):
        """
        Bloquea:
        1. Holds activos de otro cliente.
        2. Reservas nativas activas en otra SO/picking.
        """
        quants = quants.sudo().exists()

        # Los traslados internos del carrito/escáner son reservas DÉBILES:
        # mover material de ubicación no lo compromete. Antes de validar se
        # liberan para que la venta/apartado/entrega tome el lote sin chocar
        # con un SOM/INT abierto ("Carrito - API").
        weak_lot_ids = [q.lot_id.id for q in quants if q.lot_id]
        if weak_lot_ids:
            released = self.env['stock.picking']._release_cart_internal_reservations(
                weak_lot_ids,
                reason='Liberado automáticamente: el lote se está usando en '
                       'una venta o apartado.',
            )
            if released:
                quants.invalidate_recordset()

        # CANDADO ANTI-CARRERA: dos vendedores con la misma placa en sus
        # carritos podían confirmar simultáneamente (ninguno veía las move
        # lines no confirmadas del otro). El lock serializa: el segundo espera
        # aquí y, al liberarse, re-lee y SÍ ve la reserva ya confirmada.
        if quants:
            self.env.cr.execute(
                "SELECT id FROM stock_quant WHERE id IN %s FOR UPDATE",
                (tuple(quants.ids),),
            )
            quants.invalidate_recordset()

        for quant in quants:
            if not quant.lot_id:
                continue

            if quant.quantity <= 0:
                raise UserError(
                    f"El lote {quant.lot_id.name} no tiene cantidad física disponible."
                )

            if hasattr(quant, 'x_tiene_hold') and quant.x_tiene_hold:
                hold = quant.x_hold_activo_id

                # Mismo cliente = mismo PARTNER COMERCIAL (contacto, empresa o
                # dirección de entrega cuentan como uno solo). Además, el hold
                # que se está CONVIRTIENDO a SO nunca se bloquea a sí mismo.
                same_client = bool(
                    hold and partner_id
                    and hold.partner_id.commercial_partner_id.id
                    == self.env['res.partner'].browse(partner_id).commercial_partner_id.id
                )
                converting_hold_order = self.env.context.get('hold_order_id')
                own_hold = bool(
                    hold and converting_hold_order
                    and getattr(hold, 'hold_order_id', False)
                    and hold.hold_order_id.id == converting_hold_order
                )

                if hold and not same_client and not own_hold:
                    raise UserError(
                        f"El lote {quant.lot_id.name} ya está apartado para {hold.partner_id.name}.\n\n"
                        f"No se puede usar en esta operación."
                    )

            blockers = self._get_native_reservation_blockers(
                quant,
                allowed_order=allowed_order,
                allowed_pickings=allowed_pickings,
            )

            if blockers:
                docs_txt = self._format_native_reservation_blockers(blockers)

                raise UserError(
                    f"El lote {quant.lot_id.name} ya está reservado/asignado en otra operación activa.\n\n"
                    f"Producto: {quant.product_id.display_name}\n"
                    f"Ubicación: {quant.location_id.complete_name}\n"
                    f"Cantidad física: {quant.quantity:.4f}\n"
                    f"Reservado nativo actual: {quant.reserved_quantity:.4f}\n"
                    f"Documento activo: {docs_txt}\n\n"
                    f"No se puede usar el mismo lote en otra orden de venta, entrega o apartado."
                )

        return True

    def _assert_product_payload_quants_can_be_used(self, products, partner_id=False):
        quant_ids = self._get_selected_quant_ids_from_products_payload(products)

        if not quant_ids:
            return True

        quants = self.env['stock.quant'].sudo().browse(quant_ids).exists()
        return self._assert_quants_can_be_used(
            quants,
            partner_id=partner_id,
        )

    # -------------------------------------------------------------------------
    # CAMPOS COMPUTADOS / PRECIOS
    # -------------------------------------------------------------------------

    @api.depends('pricelist_id', 'pricelist_id.currency_id')
    def _compute_is_usd(self):
        for order in self:
            order.x_is_usd = bool(
                order.pricelist_id
                and order.pricelist_id.currency_id
                and order.pricelist_id.currency_id.name == 'USD'
            )

    @api.depends('x_exchange_rate_source', 'pricelist_id', 'pricelist_id.currency_id')
    def _compute_exchange_rate(self):
        for order in self:
            banorte_rate = order._get_banorte_rate()
            official_rate = order._get_official_rate()
            order.x_exchange_rate = official_rate if order.x_exchange_rate_source == 'official' else banorte_rate

    @api.onchange('x_exchange_rate_source', 'pricelist_id')
    def _onchange_exchange_rate_fields(self):
        self._compute_is_usd()
        self._compute_exchange_rate()

    def _get_banorte_rate(self):
        """TC Banorte para la orden: MISMA fuente y MISMO parser tolerante que
        el costeo de productos (last_rate_sell → last_rate, aguanta '$'/comas).
        Antes se leía solo last_rate con float() estricto: si el valor traía
        formato, caía en silencio al TC oficial (DOF) aunque la etiqueta
        siguiera diciendo 'Banorte'."""
        icp = self.env['ir.config_parameter'].sudo()
        Product = self.env['product.template']
        for key in ('banorte.last_rate_sell', 'banorte.last_rate'):
            try:
                rate = Product._parse_money_to_float(icp.get_param(key, '0'))
            except Exception:
                rate = 0.0
            if rate > 0:
                return rate

        return self._get_official_rate()

    def _get_official_rate(self):
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        mxn = self.env.ref('base.MXN', raise_if_not_found=False)

        if not usd or not mxn:
            return 1.0

        today = fields.Date.today()
        company = self.env.company

        rate_rec_usd = self.env['res.currency.rate'].sudo().search([
            ('currency_id', '=', usd.id),
            ('name', '<=', today),
            '|',
            ('company_id', '=', company.id),
            ('company_id', '=', False),
        ], order='name desc, company_id', limit=1)

        rate_rec_mxn = self.env['res.currency.rate'].sudo().search([
            ('currency_id', '=', mxn.id),
            ('name', '<=', today),
            '|',
            ('company_id', '=', company.id),
            ('company_id', '=', False),
        ], order='name desc, company_id', limit=1)

        usd_rate = rate_rec_usd.rate if rate_rec_usd else 1.0
        mxn_rate = rate_rec_mxn.rate if rate_rec_mxn else 1.0

        if usd_rate > 0:
            rate = mxn_rate / usd_rate
        else:
            rate = 0.0

        if 0 < rate < 1:
            rate = 1.0 / rate

        return rate if rate > 0 else 1.0

    x_authorized_floor_json = fields.Json(
        string='Pisos de precio autorizados',
        copy=False,
        help='Producto → precio mínimo autorizado. Se graba al aprobar una '
             'autorización de precios; bajar de ahí re-bloquea la orden.',
    )

    def _som_is_migrated_order(self):
        """PARCHE TEMPORAL órdenes migradas: una referencia de cliente con
        al menos 3 dígitos numéricos seguidos marca la orden como migrada
        y la EXENTA de la autorización de precios (sin franja de precios
        no autorizados y sin bloqueo al enviar/confirmar)."""
        self.ensure_one()
        return bool(re.search(r'\d{3}', self.client_order_ref or ''))

    @api.depends(
        'order_line.price_unit',
        'order_line.product_id',
        'pricelist_id',
        'x_price_authorization_id',
        'x_price_authorization_id.state',
        'x_authorized_floor_json',
        'client_order_ref',
    )
    def _compute_has_low_prices(self):
        # SIEMPRE con el rol del VENDEDOR de la orden: la bandera es
        # almacenada y antes se calculaba con el rol de QUIEN disparara el
        # recompute — un autorizador tocando la orden la evaluaba con
        # umbral Precio 5 y un vendedor con Precio 2: dos verdades para el
        # mismo documento.
        Product = self.env['product.template']
        for order in self:
            threshold_level = Product._get_user_threshold_level(
                user=order.user_id or self.env.user)
            if order._som_is_migrated_order():
                order.x_has_low_prices = False
                continue
            approved = bool(
                order.x_price_authorization_id
                and order.x_price_authorization_id.state == 'approved')
            floors = order.x_authorized_floor_json or {}

            currency_code = order.pricelist_id.currency_id.name or 'USD' if order.pricelist_id else 'USD'
            has_low = False

            for line in order.order_line:
                if not line.product_id or line.display_type or line.product_id.type == 'service':
                    continue

                # El piso autorizado manda SIEMPRE, aun con autorización
                # aprobada: bajar de lo autorizado re-bloquea la orden.
                floor = float(floors.get(str(line.product_id.id), 0) or 0)
                if floor > 0 and line.price_unit < (floor - 0.01):
                    has_low = True
                    break

                if approved:
                    continue

                tmpl = line.product_id.product_tmpl_id
                threshold = Product._get_price_level_value(tmpl, threshold_level, currency_code)

                if threshold > 0 and line.price_unit < (threshold - 0.01):
                    has_low = True
                    break

            order.x_has_low_prices = has_low

    def _get_violating_products(self):
        self.ensure_one()

        Product = self.env['product.template']
        threshold_level = Product._get_user_threshold_level(
            user=self.user_id or self.env.user)
        threshold_label_map = {
            'medium': 'Precio 2',
            'minimum': 'Precio 3',
            'level_4': 'Precio 4',
            'level_5': 'Precio 5',
        }
        threshold_label = threshold_label_map.get(threshold_level, threshold_level)

        currency_code = self.pricelist_id.currency_id.name or 'USD' if self.pricelist_id else 'USD'
        violating = []
        approved = bool(
            self.x_price_authorization_id
            and self.x_price_authorization_id.state == 'approved')
        floors = self.x_authorized_floor_json or {}

        for line in self.order_line:
            if not line.product_id or line.display_type or line.product_id.type == 'service':
                continue

            floor = float(floors.get(str(line.product_id.id), 0) or 0)
            if floor > 0 and line.price_unit < (floor - 0.01):
                violating.append(
                    f"{line.product_id.display_name} "
                    f"(Precio: {line.price_unit:.2f}, Precio autorizado: {floor:.2f})"
                )
                continue

            if approved:
                continue

            tmpl = line.product_id.product_tmpl_id
            threshold = Product._get_price_level_value(tmpl, threshold_level, currency_code)

            if threshold > 0 and line.price_unit < (threshold - 0.01):
                violating.append(
                    f"{line.product_id.display_name} "
                    f"(Precio: {line.price_unit:.2f}, {threshold_label}: {threshold:.2f})"
                )

        return violating

    def _som_authorized_floor_violations(self):
        """Líneas por debajo del precio YA autorizado (piso)."""
        self.ensure_one()
        floors = self.x_authorized_floor_json or {}
        if not floors:
            return []
        out = []
        for line in self.order_line:
            if not line.product_id or line.display_type:
                continue
            floor = float(floors.get(str(line.product_id.id), 0) or 0)
            if floor > 0 and line.price_unit < (floor - 0.01):
                out.append(
                    f"{line.product_id.display_name} "
                    f"(Precio: {line.price_unit:.2f}, Autorizado: {floor:.2f})"
                )
        return out

    def _som_alert_floor_violation(self, violations):
        """El vendedor bajó un precio por debajo de lo autorizado: la orden
        queda re-bloqueada y los autorizadores deben aprobar de nuevo."""
        self.ensure_one()
        listado = "\n".join(f"• {v}" for v in violations)
        self.message_post(body=Markup(
            f"<p>🚫 <b>Precio por debajo de lo autorizado</b> — la orden "
            f"queda BLOQUEADA (enviar/imprimir/confirmar) hasta contar con "
            f"una nueva autorización.</p><pre>{listado}</pre>"
        ))
        group = self.env.ref(
            'inventory_shopping_cart.group_price_authorizer',
            raise_if_not_found=False)
        if group:
            self._som_notify_users(
                self._som_group_users(group),
                f"Re-autorizar precios: {self.name}",
                f"{self.env.user.name} bajó precios por debajo de lo YA "
                f"autorizado en la orden {self.name} "
                f"(cliente {self.partner_id.display_name or ''}). La orden "
                f"está bloqueada hasta una nueva autorización.\n{listado}",
            )

    def _check_seller_low_price_block(self, action_name="realizar esta acción"):
        for order in self:
            if not order.x_has_low_prices:
                continue

            # Parche temporal: órdenes migradas (referencia con 3+ dígitos)
            # avanzan sin autorización de precios.
            if order._som_is_migrated_order():
                continue

            if self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
                continue

            violating = order._get_violating_products()

            if violating:
                raise UserError(
                    f"🚫 ACCIÓN BLOQUEADA - PRECIOS NO AUTORIZADOS\n\n"
                    f"No puede {action_name} la orden {order.name}.\n"
                    f"Productos con precios por debajo del nivel permitido para su rol:\n"
                    f"• {chr(10).join(violating)}\n\n"
                    f"Solicite autorización de precio primero."
                )

    # ─── Autorización de descuentos altos ────────────────────────────────────

    def _get_discount_auth_threshold_mxn(self):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param(
                'inventory_shopping_cart.discount_auth_threshold_mxn', '2000') or 2000.0)
        except (ValueError, TypeError):
            return 2000.0

    def _discount_amount_to_mxn(self, amount):
        """Convierte un monto en la divisa de la orden a MXN, usando el tipo de
        cambio de la orden (Banorte) si es USD, o res.currency._convert."""
        self.ensure_one()
        amount = float(amount or 0.0)
        if not amount:
            return 0.0
        mxn = self.env.ref('base.MXN', raise_if_not_found=False)
        cur = self.currency_id or (self.pricelist_id.currency_id if self.pricelist_id else False)
        if not cur or not mxn or cur.id == mxn.id or (cur.name or '') == 'MXN':
            return amount
        rate = self.x_exchange_rate or 0.0
        if (cur.name or '') == 'USD' and rate > 0:
            return amount * rate
        try:
            return cur._convert(amount, mxn, self.company_id or self.env.company,
                                fields.Date.context_today(self))
        except Exception:
            return amount

    @api.depends('order_line.discount', 'order_line.price_unit',
                 'order_line.product_uom_qty', 'currency_id', 'pricelist_id',
                 'x_exchange_rate')
    def _compute_discount_amount_mxn(self):
        for order in self:
            disc_product = getattr(
                order.company_id, 'sale_discount_product_id', False)
            total = 0.0
            for line in order.order_line:
                if line.display_type or not line.product_id:
                    continue
                disc = line.discount or 0.0
                if disc > 0:
                    total += (line.price_unit or 0.0) * (line.product_uom_qty or 0.0) * disc / 100.0
                # Línea de DESCUENTO GLOBAL (botón bajo las líneas, modo
                # importe): el wizard crea una línea con el producto de
                # descuento de la compañía y precio NEGATIVO — también es
                # descuento y también cuenta para el umbral.
                if disc_product and line.product_id.product_tmpl_id == disc_product \
                        and (line.price_unit or 0.0) < 0:
                    total += -(line.price_unit or 0.0) * (line.product_uom_qty or 0.0)
            order.x_discount_amount_mxn = order._discount_amount_to_mxn(total)

    @api.depends('x_discount_amount_mxn', 'x_discount_authorized_amount')
    def _compute_discount_needs_auth(self):
        for order in self:
            threshold = order._get_discount_auth_threshold_mxn()
            amount = order.x_discount_amount_mxn or 0.0
            authorized = order.x_discount_authorized_amount or 0.0
            order.x_discount_needs_auth = bool(
                amount >= threshold and amount > (authorized + 0.01)
            )

    x_discount_pending_request = fields.Boolean(
        string='Descuento por autorizar',
        compute='_compute_discount_pending_request',
        help='Hay descuentos capturados SIN APLICAR esperando autorización.',
    )

    @api.depends('order_line.x_requested_discount')
    def _compute_discount_pending_request(self):
        for order in self:
            order.x_discount_pending_request = any(
                (line.x_requested_discount or 0.0) > 0
                for line in order.order_line
            )

    def _som_pending_discount_amount_mxn(self):
        """Monto MXN del descuento SOLICITADO y aún no aplicado (delta sobre
        el descuento vigente de cada línea)."""
        self.ensure_one()
        total = 0.0
        for line in self.order_line:
            req = line.x_requested_discount or 0.0
            if req <= 0 or line.display_type or not line.product_id:
                continue
            delta = max(req - (line.discount or 0.0), 0.0)
            total += (line.price_unit or 0.0) * (line.product_uom_qty or 0.0) * delta / 100.0
        return self._discount_amount_to_mxn(total)

    def _som_discount_auth_auto_request(self):
        """La captura de un descuento que requiere autorización LANZA la
        solicitud sola (patrón de precios mínimos): actividad + inbox/correo
        a los autorizadores, sin que el vendedor tenga que acordarse."""
        for order in self:
            pending = order._som_pending_discount_amount_mxn()
            if pending <= 0:
                continue
            order.x_discount_auth_requested = True
            order._notify_discount_authorizers()
            order.message_post(body=Markup(
                f"<p>🔐 <b>Descuento retenido</b>: se capturó un descuento de "
                f"≈ {pending:,.2f} MXN que requiere autorización. "
                f"<b>NO se aplicó</b> a la orden; se aplicará al autorizarse. "
                f"Solicitud enviada a los Autorizadores de Precios.</p>"
            ))

    def _check_discount_authorization_block(self, action_name="realizar esta acción"):
        if self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            return
        for order in self:
            if not order.x_discount_needs_auth:
                continue
            raise UserError(
                f"🚫 ACCIÓN BLOQUEADA - DESCUENTO NO AUTORIZADO\n\n"
                f"No puede {action_name} la orden {order.name}.\n"
                f"El descuento aplicado (≈ {order.x_discount_amount_mxn:,.2f} MXN) "
                f"supera el umbral de {order._get_discount_auth_threshold_mxn():,.2f} MXN "
                f"y requiere autorización de un Autorizador de Precios.\n\n"
                f"Use el botón 'Solicitar autorización de descuento'."
            )

    def _som_group_users(self, group):
        """Usuarios de un grupo, tolerante a Odoo 19: res.groups ya no tiene
        'users'; se resuelve por el campo que exista. all_user_ids va PRIMERO
        y se UNE con user_ids: solo user_ids omite a quienes reciben el grupo
        por IMPLICACIÓN de otro grupo (autorizadores sin notificar)."""
        Users = self.env['res.users']
        if not group:
            return Users
        users = Users
        for fname in ('all_user_ids', 'user_ids', 'users'):
            if fname in group._fields:
                users |= group[fname]
        if users:
            return users.filtered(lambda u: u.active and not u.share)
        for fname in ('all_group_ids', 'group_ids', 'groups_id'):
            if fname in Users._fields:
                return Users.search([
                    (fname, 'in', group.id), ('active', '=', True)])
        return Users

    def _notify_discount_authorizers(self):
        """Actividad + mención en chatter (inbox/correo) — mismo canal doble
        que las autorizaciones de precios mínimos."""
        self.ensure_one()
        group = self.env.ref('inventory_shopping_cart.group_price_authorizer', raise_if_not_found=False)
        if not group:
            return
        pending = self._som_pending_discount_amount_mxn()
        parts = []
        if pending > 0:
            parts.append(
                f"un descuento POR APLICAR de ≈ {pending:,.2f} MXN "
                f"(retenido: no se aplica hasta autorizar)")
        if self.x_discount_needs_auth:
            parts.append(
                f"un descuento aplicado de ≈ {self.x_discount_amount_mxn:,.2f} MXN "
                f"que supera el umbral (orden BLOQUEADA)")
        note = (
            f"La orden {self.name} (cliente {self.partner_id.display_name or ''}, "
            f"vendedor {self.env.user.name}) tiene "
            f"{' y '.join(parts) or 'un descuento que requiere autorización'}. "
            f"Umbral: {self._get_discount_auth_threshold_mxn():,.2f} MXN."
        )
        users = self._som_group_users(group)
        if not users:
            _logger.warning(
                "[DISCOUNT AUTH] %s sin autorizadores a quien notificar.",
                self.name)
            return
        self._som_notify_users(
            users,
            f"Autorizar descuento: {self.name}",
            note,
        )

    def _notify_discount_seller(self, approved=True):
        self.ensure_one()
        seller = self.user_id or self.env.user
        if approved:
            summary = f"Descuento autorizado: {self.name}"
            note = (f"El descuento de ≈ {self.x_discount_amount_mxn:,.2f} MXN fue "
                    f"AUTORIZADO por {self.env.user.name}. La orden ya no está bloqueada.")
        else:
            summary = f"Descuento rechazado: {self.name}"
            note = (f"El descuento de la orden {self.name} fue RECHAZADO por "
                    f"{self.env.user.name}. Ajusta el descuento o el precio.")
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=seller.id,
            summary=summary,
            note=note,
        )

    def _discount_auth_mark_activities_done(self):
        self.ensure_one()
        acts = self.activity_ids.filtered(
            lambda a: (a.summary or '').startswith('Autorizar descuento')
        )
        for act in acts:
            try:
                act.action_feedback(feedback="Atendido")
            except Exception:
                act.unlink()

    def action_request_discount_authorization(self):
        self.ensure_one()
        if not self.x_discount_needs_auth:
            raise UserError("Esta orden no tiene un descuento que requiera autorización.")
        self.x_discount_auth_requested = True
        self._notify_discount_authorizers()
        self.message_post(body=Markup(
            f"<p>🔐 <b>Solicitud de autorización de descuento</b> "
            f"(≈ {self.x_discount_amount_mxn:,.2f} MXN) enviada a los autorizadores. "
            f"La orden está bloqueada hasta ser autorizada.</p>"
        ))
        return True

    def action_authorize_discount(self):
        self.ensure_one()
        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("Solo un Autorizador de Precios puede autorizar descuentos.")

        # APLICAR lo retenido: los descuentos solicitados pasan a la línea
        # recién ahora, con la aprobación (antes de esto NO afectaban la
        # orden — mismo patrón que los precios topados al umbral).
        pending_lines = self.order_line.filtered(
            lambda l: (l.x_requested_discount or 0.0) > 0)
        for line in pending_lines:
            line.with_context(
                som_discount_auth_apply=True,
                som_discount_clamp_done=True,
            ).write({
                'discount': line.x_requested_discount,
                'x_requested_discount': 0.0,
            })

        self.x_discount_authorized_amount = self.x_discount_amount_mxn
        self.x_discount_auth_requested = False
        self.x_discount_auth_result = 'approved'
        self._discount_auth_mark_activities_done()
        applied_note = (
            f" Se aplicaron los descuentos retenidos de {len(pending_lines)} línea(s)."
            if pending_lines else ""
        )
        self.message_post(body=Markup(
            f"<p>✅ <b>Descuento autorizado</b> (≈ {self.x_discount_amount_mxn:,.2f} MXN) "
            f"por {self.env.user.name}.{applied_note} La orden ya no está bloqueada.</p>"
        ))
        self._notify_discount_seller(approved=True)
        return True

    def action_reject_discount(self):
        self.ensure_one()
        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("Solo un Autorizador de Precios puede rechazar descuentos.")

        # DESCARTAR lo retenido: los descuentos solicitados jamás llegaron a
        # aplicarse; al rechazar simplemente se limpian.
        pending_lines = self.order_line.filtered(
            lambda l: (l.x_requested_discount or 0.0) > 0)
        if pending_lines:
            pending_lines.with_context(som_discount_clamp_done=True).write({
                'x_requested_discount': 0.0,
            })

        self.x_discount_auth_result = 'rejected'
        self.x_discount_rejected_amount = (
            self.x_discount_rejected_amount
            + (self.x_discount_amount_mxn or 0.0))
        self.x_discount_auth_requested = False
        self._discount_auth_mark_activities_done()
        discarded_note = (
            f" Los descuentos retenidos de {len(pending_lines)} línea(s) se descartaron "
            f"(nunca se aplicaron)."
            if pending_lines else ""
        )
        self.message_post(body=Markup(
            f"<p>❌ <b>Descuento rechazado</b> por {self.env.user.name}.{discarded_note}</p>"
        ))
        self._notify_discount_seller(approved=False)
        return True

    # ------------------------------------------------------------------
    # AUTORIZACIÓN PARA QUITAR EL IVA DE SERVICIOS
    # ------------------------------------------------------------------
    x_iva_exempt_state = fields.Selection([
        ('none', 'Con IVA'),
        ('requested', 'Exención solicitada'),
        ('approved', 'Exención aprobada'),
        ('rejected', 'Exención rechazada'),
    ], string="IVA de la orden", default='none', copy=False, tracking=True)

    def _som_notify_users(self, users, summary, note):
        """Actividad + mención en el chatter (inbox/correo) para cada usuario."""
        self.ensure_one()
        users = users.filtered(lambda u: u.id != self.env.user.id)
        for user in users:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                summary=summary,
                note=note,
            )
        if users.partner_id:
            self.message_post(
                body=Markup('<p><b>%s</b></p><p>%s</p>') % (summary, note),
                partner_ids=users.partner_id.ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def _som_user_can_remove_iva(self):
        """Eliminar IVA es acción DIRECTA y exclusiva de dos perfiles:
        Autorizador de Precios Mínimos y Visor del Dashboard (SOM
        Analytics). El autorizador implica al visor, así que basta el
        grupo del visor, pero se validan ambos por claridad/robustez."""
        user = self.env.user
        return (
            user.has_group('inventory_shopping_cart.group_price_authorizer')
            or user.has_group('inventory_shopping_cart.group_dashboard_viewer')
        )

    def _som_remove_iva_from_lines(self):
        """Retira el IVA 16% de TODAS las líneas de la orden."""
        self.ensure_one()
        for line in self.order_line:
            if line.product_id and not line.display_type:
                iva = line.tax_ids.filtered(
                    lambda t: t.type_tax_use == 'sale'
                    and t.amount_type == 'percent' and t.amount == 16)
                if iva:
                    line.with_context(som_skip_iva_force=True).tax_ids = [
                        (3, t.id) for t in iva]

    def action_remove_iva(self):
        """ELIMINAR IVA directo (sin flujo de solicitud): solo Autorizador
        de Precios Mínimos o Visor del Dashboard (SOM Analytics)."""
        self.ensure_one()
        if not self._som_user_can_remove_iva():
            raise UserError(
                "Solo un Autorizador de Precios Mínimos o un Visor del "
                "Dashboard (SOM Analytics) puede eliminar el IVA.")
        if self.state == 'cancel':
            raise UserError("No se puede eliminar el IVA de una orden cancelada.")
        if self.x_iva_exempt_state == 'approved':
            raise UserError("El IVA ya fue eliminado en esta orden.")
        self.x_iva_exempt_state = 'approved'
        self._som_remove_iva_from_lines()
        self.message_post(body=Markup(
            f"<p>🧾 <b>IVA ELIMINADO</b> directamente por "
            f"{self.env.user.name}. Se retiró el IVA 16% de la orden.</p>"
        ))
        if self.user_id and self.user_id != self.env.user:
            self._som_notify_users(
                self.user_id,
                f"IVA eliminado: {self.name}",
                f"{self.env.user.name} eliminó el IVA de la orden {self.name}.",
            )
        return True

    def action_request_iva_exemption(self):
        self.ensure_one()
        if self.x_iva_exempt_state == 'approved':
            raise UserError("La exención de IVA ya está aprobada en esta orden.")
        self.x_iva_exempt_state = 'requested'
        group = self.env.ref(
            'inventory_shopping_cart.group_price_authorizer',
            raise_if_not_found=False)
        if group:
            self._som_notify_users(
                self._som_group_users(group),
                f"Autorizar quitar IVA: {self.name}",
                f"La orden {self.name} (cliente {self.partner_id.display_name or ''}, "
                f"vendedor {self.env.user.name}) solicita QUITAR el IVA del 16%. "
                f"La orden conserva el IVA hasta que se apruebe.",
            )
        self.message_post(body=Markup(
            f"<p>🔐 <b>Solicitud para quitar IVA</b> enviada a los "
            f"Autorizadores de Precios por {self.env.user.name}.</p>"
        ))
        return True

    def action_approve_iva_exemption(self):
        self.ensure_one()
        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("Solo un Autorizador de Precios puede aprobar quitar el IVA.")
        if self.x_iva_exempt_state != 'requested':
            raise UserError("No hay solicitud de exención de IVA pendiente.")
        self.x_iva_exempt_state = 'approved'
        # Con la exención aprobada, se retira el IVA 16% de TODAS las líneas.
        self._som_remove_iva_from_lines()
        self.message_post(body=Markup(
            f"<p>✅ <b>Exención de IVA APROBADA</b> por "
            f"{self.env.user.name}. Se retiró el IVA 16% de la orden.</p>"
        ))
        if self.user_id:
            self._som_notify_users(
                self.user_id,
                f"Exención de IVA aprobada: {self.name}",
                f"{self.env.user.name} aprobó quitar el IVA "
                f"de la orden {self.name}.",
            )
        return True

    def action_reject_iva_exemption(self):
        self.ensure_one()
        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("Solo un Autorizador de Precios puede rechazar la solicitud.")
        if self.x_iva_exempt_state != 'requested':
            raise UserError("No hay solicitud de exención de IVA pendiente.")
        self.x_iva_exempt_state = 'rejected'
        self.message_post(body=Markup(
            f"<p>❌ <b>Exención de IVA RECHAZADA</b> por "
            f"{self.env.user.name}. La orden conserva el IVA 16%.</p>"
        ))
        if self.user_id:
            self._som_notify_users(
                self.user_id,
                f"Exención de IVA rechazada: {self.name}",
                f"{self.env.user.name} rechazó quitar el IVA "
                f"de la orden {self.name}. La orden conserva el IVA.",
            )
        return True

    def _create_invoices(self, *args, **kwargs):
        if not self.env.context.get('skip_auth_check'):
            self._check_discount_authorization_block("facturar")
        return super()._create_invoices(*args, **kwargs)

    def action_quotation_send(self):
        self._check_seller_low_price_block("enviar")
        self._check_discount_authorization_block("enviar")
        return super().action_quotation_send()

    def _sync_lot_ids_from_selected_lots(self):
        """
        Sincroniza lot_ids desde x_selected_lots antes de confirmar.
        """
        for order in self:
            for line in order.order_line:
                if line.x_selected_lots and not line.lot_ids:
                    # Solo en la PRIMERA confirmación: si la línea ya tiene
                    # movimientos vivos, lot_ids vacío significa que el
                    # vendedor QUITÓ la selección — sembrar desde el carrito
                    # aquí resucitaría material ya borrado.
                    if line.move_ids.filtered(
                            lambda m: m.state not in ('cancel',)):
                        continue
                    lot_ids = line.x_selected_lots.mapped('lot_id')
                    if lot_ids:
                        _logger.info(
                            "[CART→STONE] Sincronizando lot_ids para línea %s: %s lotes desde x_selected_lots",
                            line.id,
                            len(lot_ids),
                        )
                        line.lot_ids = [(6, 0, lot_ids.ids)]

    def _sync_stone_selection_after_confirm(self):
        """
        Tras confirmar una venta originada en el carrito, copia la selección
        real de placas hacia lot_ids / x_lot_breakdown_json de la línea de
        venta, para que el widget de selección de placas (sale_stone_selection)
        muestre las mismas placas que ya quedaron asignadas en la entrega.

        Motivo:
        El carrito llena x_selected_lots en borrador, pero sale_stone_selection
        bloquea/limpia la escritura de lot_ids mientras la orden es cotización.
        Por eso, una vez confirmada (estado sale), reconstruimos la selección
        del widget directamente desde los move lines ya asignados.

        - Lee las cantidades desde los move lines asignados por
          _assign_specific_lots, respetando placas completas y cantidades
          parciales de formato/pieza.
        - Evita doble conteo en entregas multi-paso tomando la mayor cantidad
          registrada en un solo picking por cada lote.
        - No reconstruye los pickings (skip_stone_sync_picking).
        """
        SaleOrderLine = self.env['sale.order.line']
        if 'lot_ids' not in SaleOrderLine._fields:
            return

        StockMoveLine = self.env['stock.move.line']
        qty_field = 'quantity' if 'quantity' in StockMoveLine._fields else 'qty_done'

        for order in self:
            if order.state not in ('sale', 'done'):
                continue

            for line in order.order_line:
                if line.display_type or not line.product_id:
                    continue

                if line.product_id.type not in ('product', 'consu'):
                    continue

                if not line.x_selected_lots:
                    continue

                move_lines = line.move_ids.filtered(
                    lambda m: m.state != 'cancel'
                ).mapped('move_line_ids').filtered(lambda ml: ml.lot_id)

                # Agrupar por (lote, picking) para poder deduplicar multi-paso.
                qty_by_lot_picking = {}
                for ml in move_lines:
                    key = (ml.lot_id.id, ml.picking_id.id if ml.picking_id else 0)
                    qty_by_lot_picking[key] = qty_by_lot_picking.get(key, 0.0) + float(
                        getattr(ml, qty_field, 0.0) or 0.0
                    )

                # Por lote, tomar la mayor cantidad de un solo picking.
                # En entregas multi-paso cada paso repite la misma cantidad,
                # por lo que el máximo equivale a la cantidad real seleccionada.
                qty_by_lot = {}
                for (lot_id, _pick_id), qty in qty_by_lot_picking.items():
                    if qty > qty_by_lot.get(lot_id, 0.0):
                        qty_by_lot[lot_id] = qty

                # Fallback: si todavía no hay move lines, usar x_selected_lots
                # PREFIRIENDO la parcialidad del desglose original (llave de
                # lote o de quant). Tomar quant.quantity a ciegas inflaba la
                # asignación al quant COMPLETO (100 en vez de los 50
                # vendidos) cuando la reserva aún no existía.
                if not qty_by_lot:
                    original_bd = line.x_lot_breakdown_json or {}
                    for quant in line.x_selected_lots:
                        if not quant.lot_id:
                            continue
                        qty = None
                        raw = original_bd.get(str(quant.lot_id.id))
                        if raw is None:
                            raw = original_bd.get(str(quant.id))
                        if raw is not None:
                            try:
                                qty = float(raw or 0.0)
                            except Exception:
                                qty = None
                        if qty is None:
                            qty = quant.quantity or 0.0
                        qty_by_lot[quant.lot_id.id] = qty_by_lot.get(
                            quant.lot_id.id, 0.0
                        ) + qty

                lot_ids = list(qty_by_lot.keys())
                if not lot_ids:
                    continue

                # Breakdown re-keado por lot_id solo para formato/pieza,
                # que es lo que lee el widget de selección de placas.
                lot_breakdown = {}
                for lot in self.env['stock.lot'].browse(lot_ids):
                    tipo = str(getattr(lot, 'x_tipo', '') or 'placa').lower()
                    if tipo in ('formato', 'pieza'):
                        lot_breakdown[str(lot.id)] = qty_by_lot.get(lot.id, 0.0)

                vals = {}
                if set(line.lot_ids.ids) != set(lot_ids):
                    vals['lot_ids'] = [(6, 0, lot_ids)]
                if lot_breakdown:
                    vals['x_lot_breakdown_json'] = lot_breakdown

                if vals:
                    _logger.info(
                        "[CART→STONE] Sincronizando selección post-confirmación en línea %s: %s lotes",
                        line.id,
                        len(lot_ids),
                    )
                    line.with_context(
                        skip_stone_sync_picking=True,
                        skip_stone_sync_so=True,
                    ).write(vals)

    def _som_capture_confirm_rate(self):
        for order in self:
            if not order.x_confirm_exchange_rate:
                order.x_confirm_exchange_rate = order.x_exchange_rate or 0.0

    def action_confirm(self):
        self._som_capture_confirm_rate()

        # ÓRDENES MIGRADAS: conservar su FECHA histórica. El core pisa
        # date_order con now() al confirmar, y las ventas migradas (con
        # fecha pasada capturada) brincaban al mes actual ensuciando SOM
        # Analytics, que filtra por date_order. Mismo marcador del parche
        # de migración: referencia con 3+ dígitos.
        """
        Override:
        1. Valida precios bajos.
        2. Bloquea quants/lotes ya reservados nativamente en otra SO/picking.
        3. Sincroniza lot_ids.
        4. Confirma.
        5. Asigna lotes específicos.
        6. Sincroniza la selección de placas hacia la orden de venta.
        """
        if not self.env.context.get('skip_auth_check'):
            self._check_seller_low_price_block("confirmar")
            self._check_discount_authorization_block("confirmar")

        for order in self:
            selected_quants = order._get_selected_quants_from_order()
            if selected_quants:
                order._assert_quants_can_be_used(
                    selected_quants,
                    partner_id=order.partner_id.id,
                    allowed_order=order,
                )

        self._sync_lot_ids_from_selected_lots()

        res = super().action_confirm()

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
                            breakdown_int = {
                                int(k): float(v)
                                for k, v in line.x_lot_breakdown_json.items()
                            }
                        except (TypeError, ValueError, AttributeError) as e:
                            _logger.warning("Error parseando breakdown: %s", e)

                    order._assign_specific_lots(
                        pickings,
                        line.product_id,
                        line.x_selected_lots,
                        breakdown=breakdown_int,
                    )

        # Copiar la selección real a lot_ids/breakdown para que el widget
        # de selección de placas de la orden de venta muestre las placas.
        self._sync_stone_selection_after_confirm()

        return res

    @api.model_create_multi
    def create(self, vals_list):
        # El default nativo puede llegar traducido ("Nuevo") según el idioma
        # del cliente web; comparar solo contra 'New' dejaba pasar folios
        # S000xx de la secuencia estándar mezclados con los COT/.
        default_names = {'New', 'Nuevo', _('New')}
        for vals in vals_list:
            if vals.get('name', 'New') in default_names:
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.quotation') or 'New'

        return super().create(vals_list)

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id_custom_prices(self):
        if not self.pricelist_id:
            return

        self._compute_is_usd()
        self._compute_exchange_rate()

        currency_name = self.pricelist_id.currency_id.name or 'USD'
        Product = self.env['product.template']

        old_currency = (
            self._origin.pricelist_id.currency_id.name
            if self._origin and self._origin.pricelist_id else False
        )
        rate = self.x_exchange_rate or 0.0

        for line in self.order_line:
            if not line.product_id or line.display_type:
                continue

            if line.x_price_selector == 'custom':
                # Precio personalizado: se convierte por TC al cambiar de
                # divisa (antes se quedaba con el número tal cual, absurdo
                # al pasar MXN⇄USD).
                if (
                    old_currency and old_currency != currency_name
                    and rate > 0 and line.price_unit
                ):
                    if old_currency == 'USD' and currency_name == 'MXN':
                        line.price_unit = line.price_unit * rate
                    elif old_currency == 'MXN' and currency_name == 'USD':
                        line.price_unit = line.price_unit / rate
                continue

            tmpl = line.product_id.product_tmpl_id
            new_price = Product._get_price_level_value(tmpl, line.x_price_selector, currency_name)

            if new_price > 0:
                line.price_unit = new_price

    def write(self, vals):
        # ÓRDENES MIGRADAS: el core reescribe date_order al confirmar
        # (now() junto con state='sale'); para una orden migrada eso
        # destruye su fecha histórica y ensucia el mes actual en
        # Analytics — se descarta SOLO ese pisotón automático. Las
        # ediciones manuales de la fecha (write sin cambio de estado)
        # pasan normal: así se captura la fecha histórica.
        if 'date_order' in vals \
                and vals.get('state') in ('sale', 'done') \
                and not self.env.context.get(
                    'som_allow_migrated_date_change'):
            keep = self.filtered(
                lambda o: hasattr(o, '_som_is_migrated_order')
                and o._som_is_migrated_order() and o.date_order)
            if keep:
                others = self - keep
                vals_no_date = {k: v for k, v in vals.items()
                                if k != 'date_order'}
                if others:
                    super(SaleOrder, others).write(vals)
                if vals_no_date:
                    super(SaleOrder, keep).write(vals_no_date)
                return True

        # La divisa solo puede cambiarse mientras no haya entrega validada
        # ni factura publicada (el TC se congela con la entrega).
        if 'pricelist_id' in vals:
            for order in self:
                if (
                    order.x_pricelist_locked
                    and vals['pricelist_id'] != order.pricelist_id.id
                ):
                    raise UserError(
                        f"La divisa de la orden {order.name} ya está "
                        f"CONGELADA (hay entrega validada o factura "
                        f"publicada) y no puede cambiarse."
                    )

            # El core de Odoo bloquea cambiar la lista en órdenes en estado
            # 'sale' sin excepción posible ("You cannot change the pricelist
            # of a confirmed order"). Aquí el candado REAL es
            # x_pricelist_locked (entrega/factura), así que para órdenes
            # confirmadas NO bloqueadas se aplica el cambio rodeando ese
            # guard con un estado transitorio (sin tracking para no
            # ensuciar el chatter).
            confirmed = self.filtered(
                lambda o: o.state == 'sale'
                and vals['pricelist_id'] != o.pricelist_id.id)
            if confirmed:
                pl_id = vals.pop('pricelist_id')
                res = super().write(vals) if vals else True
                pl = self.env['product.pricelist'].browse(pl_id)
                for order in self:
                    if order.pricelist_id.id == pl_id:
                        continue
                    ctx_order = order.with_context(tracking_disable=True)
                    sup = super(SaleOrder, ctx_order)
                    if order.state == 'sale':
                        sup.write({'state': 'draft'})
                        sup.write({'pricelist_id': pl_id})
                        sup.write({'state': 'sale'})
                    else:
                        sup.write({'pricelist_id': pl_id})
                    order.message_post(body=Markup(
                        f"<p>💱 <b>Divisa/lista de precios cambiada</b> a "
                        f"<b>{pl.display_name}</b> por {self.env.user.name} "
                        f"(orden confirmada sin entrega: permitido; el TC "
                        f"se congela con la entrega).</p>"
                    ))
                return res
        return super().write(vals)

    @api.model
    def _som_recompute_low_price_flags(self):
        """Recalcula x_has_low_prices de las órdenes activas con la regla
        nueva (rol del VENDEDOR de la orden). Corre en cada -u: banderas
        almacenadas con el criterio viejo quedaban pegadas."""
        orders = self.search([('state', 'in', ('draft', 'sent', 'sale'))])
        orders._compute_has_low_prices()
        _logger.info(
            '[PRECIOS] Bandera de precios bajos recalculada en %s órdenes '
            'activas.', len(orders))
        return True

    def action_request_authorization(self):
        self.ensure_one()

        # Aplica en cotizaciones Y en órdenes confirmadas: el vendedor debe
        # poder guardar siempre y solicitar autorización en cualquier estado
        # activo de la orden.
        if self.state not in ['draft', 'sent', 'sale']:
            raise UserError(
                "Solo se puede solicitar autorización de precios en "
                "cotizaciones u órdenes de venta activas."
            )

        Product = self.env['product.template']
        # El umbral se evalúa con el rol del VENDEDOR de la orden — la
        # autorización protege SU venta. Antes se evaluaba con el rol de
        # quien daba clic: un autorizador (umbral Precio 5) no 'veía'
        # violaciones y el botón tronaba aunque la orden estuviera
        # bloqueada para el vendedor.
        threshold_level = Product._get_user_threshold_level(
            user=self.user_id or self.env.user)
        currency_code = self.pricelist_id.currency_id.name or 'USD'
        product_prices = {}
        product_groups = {}
        detail_rows = []
        has_low = False

        for line in self.order_line:
            if not line.product_id or line.display_type:
                continue

            tmpl = line.product_id.product_tmpl_id
            threshold = Product._get_price_level_value(tmpl, threshold_level, currency_code)

            if threshold > 0 and line.price_unit < (threshold - 0.01):
                has_low = True
                pid_str = str(line.product_id.id)
                product_prices[pid_str] = line.price_unit
                detail_rows.append(
                    '• %s: precio %.2f vs mínimo permitido %.2f %s '
                    '(faltan %.2f)' % (
                        line.product_id.display_name, line.price_unit,
                        threshold, currency_code,
                        threshold - line.price_unit))

                if pid_str not in product_groups:
                    product_groups[pid_str] = {
                        'name': line.product_id.display_name,
                        'lots': [],
                        'total_quantity': 0,
                    }

                product_groups[pid_str]['total_quantity'] += line.product_uom_qty

        if not has_low:
            threshold_labels = {
                'high': 'Precio 1', 'medium': 'Precio 2',
                'minimum': 'Precio 3', 'level_4': 'Precio 4',
                'level_5': 'Precio 5',
            }
            raise UserError(
                "No hay precios por debajo del nivel permitido del vendedor "
                "de la orden (%s, umbral %s): no se requiere autorización.\n\n"
                "Si la orden aparece bloqueada, guarda cualquier cambio para "
                "recalcular la bandera de precios." % (
                    (self.user_id.name or 'sin vendedor'),
                    threshold_labels.get(threshold_level, threshold_level)))

        auth = self.env['price.authorization'].create({
            'seller_id': self.env.user.id,
            'operation_type': 'sale',
            'partner_id': self.partner_id.id,
            'project_id': self.x_project_id.id,
            'currency_code': currency_code,
            # note es un campo HTML: a texto plano para que las notas de la
            # autorización no muestren <div>/&nbsp; crudos.
            'notes': f"Solicitud desde Orden Manual {self.name}. "
                     f"{html2plaintext(self.note) if self.note else ''}",
            'sale_order_id': self.id,
            'temp_data': {
                'source': 'manual_order',
                'sale_order_id': self.id,
                'product_groups': product_groups,
                'architect_id': self.x_architect_id.id,
            },
        })

        self.x_price_authorization_id = auth.id

        for pid_str, group in product_groups.items():
            product = self.env['product.product'].browse(int(pid_str))
            tmpl = product.product_tmpl_id

            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': int(pid_str),
                'quantity': group['total_quantity'],
                'lot_count': 0,
                'requested_price': product_prices[pid_str],
                'authorized_price': product_prices[pid_str],
                'medium_price': Product._get_price_level_value(tmpl, 'medium', currency_code),
                'minimum_price': Product._get_price_level_value(tmpl, 'minimum', currency_code),
                'level_4_price': Product._get_price_level_value(tmpl, 'level_4', currency_code),
                'level_5_price': Product._get_price_level_value(tmpl, 'level_5', currency_code),
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'price.authorization',
            'res_id': auth.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_add_from_cart(self):
        self.ensure_one()

        if self.state not in ['draft', 'sent']:
            raise UserError("Solo puede agregar items en estado Borrador.")

        cart_items = self.env['shopping.cart'].search([
            ('user_id', '=', self.env.user.id),
        ])

        if not cart_items:
            raise UserError("Su carrito de compras está vacío.")

        grouped_items = {}

        for item in cart_items:
            self._assert_quants_can_be_used(
                item.quant_id,
                partner_id=self.partner_id.id,
                allowed_order=self,
            )

            if any(
                line.x_selected_lots and item.quant_id.id in line.x_selected_lots.ids
                for line in self.order_line
            ):
                continue

            prod_id = item.product_id.id

            if prod_id not in grouped_items:
                grouped_items[prod_id] = {
                    'product_obj': item.product_id,
                    'total_qty': 0.0,
                    'lots': [],
                    'breakdown': {},
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
            price_unit = self.env['product.template']._get_price_level_value(
                product.product_tmpl_id, 'high', currency_code,
            )

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
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    },
                },
            }

        raise UserError("No se pudieron agregar los items.")

    @staticmethod
    def _resolve_partner_addresses(env, partner_id):
        partner = env['res.partner'].browse(partner_id)
        addr = partner.address_get(['delivery', 'invoice'])
        return addr.get('invoice', partner_id), addr.get('delivery', partner_id)

    @api.model
    def _create_cart_price_authorization(
        self,
        partner_id,
        products,
        services,
        notes,
        currency_code,
        apply_tax,
        project_id=None,
        architect_id=None,
    ):
        """
        Crea la solicitud de autorización de precio para una venta desde el
        carrito. Al aprobarse, price.authorization._process_approved_authorization
        crea y confirma la orden de venta a partir de temp_data.
        """
        Quant = self.env['stock.quant'].sudo()
        Product = self.env['product.template']

        product_groups = {}
        product_prices = {}

        for pd in (products or []):
            product = self.env['product.product'].browse(pd['product_id'])

            if not product.exists():
                continue

            pid_str = str(pd['product_id'])
            product_prices[pid_str] = float(pd.get('price_unit') or 0.0)

            breakdown = {
                str(l['id']): float(l['quantity'])
                for l in pd.get('lots_breakdown', [])
            }

            lots = []
            for quant_id in pd.get('selected_lots', []):
                quant = Quant.browse(int(quant_id))

                if not quant.exists():
                    continue

                lots.append({
                    'id': quant.id,
                    'lot_name': quant.lot_id.name if quant.lot_id else '',
                    'quantity': breakdown.get(str(quant.id), quant.quantity or 0.0),
                })

            product_groups[pid_str] = {
                'name': product.display_name,
                'lots': lots,
                'total_quantity': float(pd.get('quantity') or 0.0),
                'to_be_purchased': bool(pd.get('to_be_purchased')),
            }

        auth = self.env['price.authorization'].create({
            'seller_id': self.env.user.id,
            'operation_type': 'sale',
            'partner_id': partner_id,
            'project_id': project_id,
            'currency_code': currency_code,
            'notes': notes or '',
            'temp_data': {
                'source': 'cart',
                'product_groups': product_groups,
                'services': services or [],
                'apply_tax': apply_tax,
                'architect_id': architect_id,
            },
        })

        for pid_str, group in product_groups.items():
            product = self.env['product.product'].browse(int(pid_str))
            tmpl = product.product_tmpl_id
            requested_price = product_prices.get(pid_str, 0.0)

            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': int(pid_str),
                'quantity': group['total_quantity'],
                'lot_count': len(group['lots']),
                'requested_price': requested_price,
                'authorized_price': requested_price,
                'medium_price': Product._get_price_level_value(tmpl, 'medium', currency_code),
                'minimum_price': Product._get_price_level_value(tmpl, 'minimum', currency_code),
                'level_4_price': Product._get_price_level_value(tmpl, 'level_4', currency_code),
                'level_5_price': Product._get_price_level_value(tmpl, 'level_5', currency_code),
            })

        return auth

    @api.model
    def create_from_shopping_cart(
        self,
        partner_id=None,
        products=None,
        services=None,
        notes=None,
        pricelist_id=None,
        apply_tax=True,
        project_id=None,
        architect_id=None,
    ):
        if not partner_id:
            raise UserError("El cliente es obligatorio.")

        # Regla cliente→proyectos: validación en servidor.
        self.env['stock.quant']._som_assert_project_of_partner(partner_id, project_id)

        try:
            if not pricelist_id:
                pricelist_id = self.env['res.partner'].browse(partner_id).property_product_pricelist.id

                if not pricelist_id:
                    raise UserError("No se ha definido una lista de precios.")

            pricelist = self.env['product.pricelist'].browse(pricelist_id)
            currency_code = pricelist.currency_id.name
            prices_map = {
                str(p['product_id']): p['price_unit']
                for p in (products or [])
            }

            # Validar lotes antes de cualquier otra cosa para no crear una
            # solicitud de autorización sobre lotes que ya no se pueden usar.
            self._assert_product_payload_quants_can_be_used(
                products,
                partner_id=partner_id,
            )

            # No se exenta a los autorizadores: check_price_authorization_needed
            # aplica el umbral según el rol (vendedor: P2, mayorista: P4,
            # autorizador: P5). Debajo de su umbral, todos requieren solicitud.
            # PRECIOS BAJO EL UMBRAL: la orden SE CREA SIEMPRE — jamás se
            # pierde la captura. Los precios bajos se TOPAN al umbral del rol
            # (el precio más alto) y la solicitud de autorización nace ligada
            # a la orden: al aprobarse, los precios BAJAN a lo solicitado
            # (mismo mecanismo que la solicitud desde orden manual). Antes el
            # flujo desviaba a solo-autorización y el vendedor perdía todo.
            requested_low_prices = {}
            if not self.env.context.get('skip_auth_check'):
                auth_result = self.env['product.template'].check_price_authorization_needed(
                    prices_map,
                    currency_code,
                )

                if auth_result.get('needs_authorization'):
                    Product = self.env['product.template']
                    threshold_level = Product._get_user_threshold_level()
                    for coll in (products or []), (services or []):
                        for pd in coll:
                            rec = self.env['product.product'].browse(pd['product_id'])
                            if not rec.exists():
                                continue
                            threshold = Product._get_price_level_value(
                                rec.product_tmpl_id, threshold_level, currency_code)
                            price = float(pd.get('price_unit') or 0.0)
                            if threshold > 0 and price < (threshold - 0.01):
                                requested_low_prices[str(pd['product_id'])] = price
                                pd['price_unit'] = threshold

            company_id = self.env.company.id
            invoice_id, shipping_id = self._resolve_partner_addresses(self.env, partner_id)

            sale_order = self.with_context(skip_auth_check=True).create({
                'partner_id': partner_id,
                'partner_invoice_id': invoice_id,
                'partner_shipping_id': shipping_id,
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
                    str(l['id']): float(l['quantity'])
                    for l in pd.get('lots_breakdown', [])
                } if pd.get('lots_breakdown') else {}

                line_vals = {
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
                }

                # Material sin existencia / "mandar a pedir": la reserva propaga
                # la cantidad manual y solicita marcar la línea para envío a
                # compra. El campo solo existe si stock_transit_allocation está
                # instalado, por eso la comprobación es defensiva.
                if pd.get('to_be_purchased') and 'auto_transit_assign' in self.env['sale.order.line']._fields:
                    line_vals['auto_transit_assign'] = True

                # Máscara comercial (hold → SO): nombre personalizado de la
                # venta. Se escribe también en name para que TODOS los
                # documentos impriman la máscara y no el nombre real.
                if pd.get('mask_name') and 'x_mask_name' in self.env['sale.order.line']._fields:
                    line_vals['x_mask_name'] = pd['mask_name']
                    line_vals['name'] = pd['mask_name']

                self.env['sale.order.line'].create(line_vals)

            for sd in (services or []):
                rec = self.env['product.product'].browse(sd['product_id'])
                tax_ids = [(6, 0, rec.taxes_id.ids)] if apply_tax else [(5, 0, 0)]

                service_vals = {
                    'order_id': sale_order.id,
                    'name': rec.get_product_multiline_description_sale() or rec.name,
                    'product_id': rec.id,
                    'product_uom_id': rec.uom_id.id,
                    'product_uom_qty': sd['quantity'],
                    'price_unit': sd['price_unit'],
                    'tax_ids': tax_ids,
                    'company_id': company_id,
                    'x_price_selector': 'custom',
                }
                if sd.get('mask_name') and 'x_mask_name' in self.env['sale.order.line']._fields:
                    service_vals['x_mask_name'] = sd['mask_name']
                    service_vals['name'] = sd['mask_name']

                self.env['sale.order.line'].create(service_vals)

            sale_order._sync_lot_ids_from_selected_lots()

            sale_order.invalidate_recordset()
            sale_order.with_context(skip_auth_check=True).action_confirm()

            clamp_message = ''
            if requested_low_prices:
                Product = self.env['product.template']
                qty_by_pid = {}
                for coll in (products or []), (services or []):
                    for pd in coll:
                        pid_str = str(pd['product_id'])
                        if pid_str in requested_low_prices:
                            qty_by_pid[pid_str] = qty_by_pid.get(pid_str, 0.0) \
                                + float(pd.get('quantity') or 0.0)
                auth = self.env['price.authorization'].create({
                    'seller_id': self.env.user.id,
                    'operation_type': 'sale',
                    'partner_id': partner_id,
                    'project_id': project_id,
                    'currency_code': currency_code,
                    'notes': (
                        'Solicitud automática desde carrito: la orden '
                        f'{sale_order.name} se creó con los precios TOPADOS '
                        'al umbral del rol; al aprobarse bajarán a lo '
                        'solicitado.'
                    ),
                    'sale_order_id': sale_order.id,
                    'temp_data': {
                        'source': 'manual_order',
                        'sale_order_id': sale_order.id,
                        'architect_id': architect_id,
                    },
                })
                sale_order.x_price_authorization_id = auth.id
                for pid_str, req_price in requested_low_prices.items():
                    product = self.env['product.product'].browse(int(pid_str))
                    tmpl = product.product_tmpl_id
                    self.env['price.authorization.line'].create({
                        'authorization_id': auth.id,
                        'product_id': int(pid_str),
                        'quantity': qty_by_pid.get(pid_str, 0.0),
                        'lot_count': 0,
                        'requested_price': req_price,
                        'authorized_price': req_price,
                        'medium_price': Product._get_price_level_value(tmpl, 'medium', currency_code),
                        'minimum_price': Product._get_price_level_value(tmpl, 'minimum', currency_code),
                        'level_4_price': Product._get_price_level_value(tmpl, 'level_4', currency_code),
                        'level_5_price': Product._get_price_level_value(tmpl, 'level_5', currency_code),
                    })
                clamp_message = (
                    'Precios por debajo del nivel permitido: la orden se '
                    'guardó con el precio del umbral y se creó la solicitud '
                    f'{auth.name}; al aprobarse, los precios bajarán a lo '
                    'solicitado.'
                )

            return {
                'success': True,
                'order_id': sale_order.id,
                'order_name': sale_order.name,
                'price_clamped': bool(requested_low_prices),
                'message': clamp_message,
            }

        except UserError:
            # Errores de negocio legibles: propagar tal cual (antes se
            # doble-envolvían con "Error al procesar la orden: ...").
            raise
        except Exception as e:
            _logger.error("Error en create_from_shopping_cart: %s", str(e), exc_info=True)
            raise UserError(f"Error al procesar la orden: {str(e)}")

    def _assign_specific_lots(self, pickings, product, selected_quants, breakdown=None):
        """
        Asigna lotes específicos a move lines del picking.

        Bloquea cualquier quant que ya esté reservado en otra operación activa.
        """
        sale_order = self._resolve_sale_order_from_pickings(pickings)
        cart_owner_id = sale_order.user_id.id if sale_order and sale_order.user_id else self.env.user.id

        selected_quants = selected_quants.sudo().exists()

        if selected_quants:
            self._assert_quants_can_be_used(
                selected_quants,
                partner_id=sale_order.partner_id.id if sale_order and sale_order.partner_id else False,
                allowed_order=sale_order,
                allowed_pickings=pickings,
            )

        if not breakdown:
            sample_move = pickings.mapped('move_ids').filtered(
                lambda m: m.product_id.id == product.id
            )[:1]

            if sample_move and sample_move.sale_line_id and sample_move.sale_line_id.x_lot_breakdown_json:
                try:
                    breakdown = {
                        int(k): float(v)
                        for k, v in sample_move.sale_line_id.x_lot_breakdown_json.items()
                    }
                except Exception:
                    pass

        for picking in pickings:
            if picking.state in ['done', 'cancel']:
                continue

            for move in picking.move_ids.filtered(lambda m: m.product_id.id == product.id):
                # El unlink de las líneas autoasignadas NO puede fallar en
                # silencio: crear las líneas exactas ENCIMA de las automáticas
                # duplica demanda y reserva en la entrega.
                if move.move_line_ids:
                    try:
                        move.move_line_ids.unlink()
                    except Exception as e:
                        _logger.exception(
                            "[ASSIGN_LOTS] No se pudieron limpiar las líneas "
                            "autoasignadas del move %s.", move.id,
                        )
                        raise UserError(
                            f"No se pudo preparar la entrega de {product.display_name}: "
                            f"las reservas automáticas no pudieron liberarse ({e}). "
                            "Revisa el picking antes de confirmar."
                        )

                remaining = move.product_uom_qty
                failed_lots = []

                for quant in selected_quants:
                    if quant.product_id.id != product.id or remaining <= 0:
                        continue

                    tipo = 'placa'

                    if quant.lot_id and hasattr(quant.lot_id, 'x_tipo') and quant.lot_id.x_tipo:
                        tipo = str(quant.lot_id.x_tipo).lower()

                    if 'formato' in tipo or 'pieza' in tipo:
                        if breakdown and quant.id in breakdown:
                            qty = breakdown[quant.id]
                        else:
                            cart_item = self.env['shopping.cart'].search([
                                ('user_id', '=', cart_owner_id),
                                ('quant_id', '=', quant.id),
                            ], limit=1)
                            qty = cart_item.quantity if cart_item else quant.quantity
                    else:
                        qty = quant.quantity

                    reserve = min(qty, remaining)

                    if reserve <= 0.001:
                        continue

                    source_location_id = quant.location_id.id

                    try:
                        self.env['stock.move.line'].create({
                            'move_id': move.id,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'lot_id': quant.lot_id.id,
                            'quantity': reserve,
                            'location_id': source_location_id,
                            'location_dest_id': move.location_dest_id.id,
                            'product_uom_id': product.uom_id.id,
                        })

                        remaining -= reserve

                        _logger.debug(
                            "[ASSIGN_LOTS] Lote %s: %s %s desde %s (tipo=%s)",
                            quant.lot_id.name,
                            reserve,
                            product.uom_id.name,
                            quant.location_id.complete_name,
                            tipo,
                        )

                    except Exception as e:
                        _logger.exception(
                            "Error reservando lote %s desde %s",
                            quant.lot_id.name,
                            quant.location_id.complete_name,
                        )
                        failed_lots.append(f"{quant.lot_id.name} ({e})")

                # Una placa que no se pudo reservar NO puede omitirse en
                # silencio: la orden se confirmaba "bien" con la entrega
                # incompleta y nadie se enteraba hasta el embarque.
                if failed_lots:
                    raise UserError(
                        "No se pudieron reservar estas placas para la entrega de "
                        f"{product.display_name}:\n- " + "\n- ".join(failed_lots) +
                        "\n\nCorrige el problema y vuelve a confirmar."
                    )

    def _clear_auto_assigned_lots(self):
        if PickingLotCleaner:
            cleaner = PickingLotCleaner(self.env)

            for order in self:
                if order.picking_ids:
                    cleaner.clear_pickings_lots(order.picking_ids)

class SaleOrderDiscountWizard(models.TransientModel):
    _inherit = 'sale.order.discount'

    def action_apply_discount(self):
        """Botón de DESCUENTO GLOBAL (bajo las líneas, arriba de los totales).

        - Modo porcentaje sobre líneas: escribe 'discount' por línea → el
          clamp de la línea lo retiene y auto-solicita (no se aplica hasta
          autorizar; nada extra que hacer aquí).
        - Modo importe / porcentaje global: crea una línea NEGATIVA con el
          producto de descuento de la compañía; esa línea cuenta para el
          umbral — si dispara autorización, la solicitud se lanza sola con
          la misma notificación y la orden queda BLOQUEADA hasta autorizar.
        """
        res = super().action_apply_discount()
        for order in self.sale_order_id:
            if order.x_discount_needs_auth and not order.x_discount_auth_requested:
                order.x_discount_auth_requested = True
                order._notify_discount_authorizers()
                order.message_post(body=Markup(
                    f"<p>🔐 <b>Solicitud de autorización de descuento</b> "
                    f"(≈ {order.x_discount_amount_mxn:,.2f} MXN, descuento "
                    f"global) enviada a los autorizadores. La orden está "
                    f"bloqueada hasta ser autorizada.</p>"
                ))
        return res
