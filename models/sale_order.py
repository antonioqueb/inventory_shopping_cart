# -*- coding: utf-8 -*-
# models/sale_order.py

import math
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.stock_lot_dimensions.models.utils.picking_cleaner import PickingLotCleaner
except ImportError:
    PickingLotCleaner = None


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

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
        ('high', 'Precio 1'),
        ('medium', 'Precio 2'),
        ('custom', 'Precio Personalizado'),
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

    x_price_level_currency = fields.Char(
        string='Moneda Nivel Precio',
        compute='_compute_price_level_values',
    )

    x_can_use_custom_price = fields.Boolean(
        string='Puede usar precio personalizado',
        compute='_compute_x_can_use_custom_price',
    )

    @api.depends_context('uid')
    def _compute_x_can_use_custom_price(self):
        for line in self:
            line.x_can_use_custom_price = True

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
            elif tmpl:
                line.x_price_1_value = tmpl.x_price_usd_1
                line.x_price_2_value = tmpl.x_price_usd_2
            else:
                line.x_price_1_value = 0.0
                line.x_price_2_value = 0.0

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
    )

    x_architect_id = fields.Many2one(
        'res.partner',
        string='Arquitecto',
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

        if allowed_pickings:
            allowed_picking_ids = set(allowed_pickings.ids)
            blockers = blockers.filtered(lambda ml: ml.picking_id.id not in allowed_picking_ids)

        if allowed_order:
            blockers = blockers.filtered(
                lambda ml: (
                    not ml.move_id
                    or not ml.move_id.sale_line_id
                    or ml.move_id.sale_line_id.order_id.id != allowed_order.id
                )
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

        for quant in quants:
            if not quant.lot_id:
                continue

            if quant.quantity <= 0:
                raise UserError(
                    f"El lote {quant.lot_id.name} no tiene cantidad física disponible."
                )

            if hasattr(quant, 'x_tiene_hold') and quant.x_tiene_hold:
                hold = quant.x_hold_activo_id

                if hold and (not partner_id or hold.partner_id.id != partner_id):
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
        try:
            rate = float(self.env['ir.config_parameter'].sudo().get_param('banorte.last_rate', '0'))
            if rate > 0:
                return rate
        except (ValueError, TypeError):
            pass

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

    @api.depends(
        'order_line.price_unit',
        'order_line.product_id',
        'pricelist_id',
        'x_price_authorization_id',
        'x_price_authorization_id.state',
    )
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
                violating.append(
                    f"{line.product_id.display_name} "
                    f"(Precio: {line.price_unit:.2f}, Medio: {medium:.2f})"
                )

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

    def _sync_lot_ids_from_selected_lots(self):
        """
        Sincroniza lot_ids desde x_selected_lots antes de confirmar.
        """
        for order in self:
            for line in order.order_line:
                if line.x_selected_lots and not line.lot_ids:
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

                # Fallback: si todavía no hay move lines, usar x_selected_lots.
                if not qty_by_lot:
                    for quant in line.x_selected_lots:
                        if quant.lot_id:
                            qty_by_lot[quant.lot_id.id] = qty_by_lot.get(
                                quant.lot_id.id, 0.0
                            ) + (quant.quantity or 0.0)

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

    def action_confirm(self):
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
                        except Exception as e:
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
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.quotation') or 'New'

        return super().create(vals_list)

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id_custom_prices(self):
        if not self.pricelist_id:
            return

        self._compute_is_usd()
        self._compute_exchange_rate()

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
        product_prices = {}
        product_groups = {}
        has_low = False

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
                        'total_quantity': 0,
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
                'architect_id': self.x_architect_id.id,
            },
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

            is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')

            if not self.env.context.get('skip_auth_check') and not is_authorizer:
                auth_result = self.env['product.template'].check_price_authorization_needed(
                    prices_map,
                    currency_code,
                )

                if auth_result.get('needs_authorization'):
                    return {
                        'needs_authorization': True,
                        'message': 'Se detectaron precios por debajo del nivel medio. Se requiere autorización.',
                    }

            self._assert_product_payload_quants_can_be_used(
                products,
                partner_id=partner_id,
            )

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

            sale_order._sync_lot_ids_from_selected_lots()

            sale_order.invalidate_recordset()
            sale_order.with_context(skip_auth_check=True).action_confirm()

            return {
                'success': True,
                'order_id': sale_order.id,
                'order_name': sale_order.name,
            }

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
                try:
                    if move.move_line_ids:
                        move.move_line_ids.unlink()
                except Exception:
                    pass

                remaining = move.product_uom_qty

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

                        _logger.info(
                            "[ASSIGN_LOTS] Lote %s: %s %s desde %s (tipo=%s)",
                            quant.lot_id.name,
                            reserve,
                            product.uom_id.name,
                            quant.location_id.complete_name,
                            tipo,
                        )

                    except Exception as e:
                        _logger.error(
                            "Error reservando lote %s desde %s: %s",
                            quant.lot_id.name,
                            quant.location_id.complete_name,
                            e,
                        )

    def _clear_auto_assigned_lots(self):
        if PickingLotCleaner:
            cleaner = PickingLotCleaner(self.env)

            for order in self:
                if order.picking_ids:
                    cleaner.clear_pickings_lots(order.picking_ids)