# -*- coding: utf-8 -*-
import math
from odoo import models, fields, api
from odoo.exceptions import UserError


class PriceAuthorization(models.Model):
    _name = 'price.authorization'
    _description = 'Autorización de Precios Mínimos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Referencia',
        required=True,
        copy=False,
        readonly=True,
        default='Nuevo',
    )

    seller_id = fields.Many2one(
        'res.users',
        string='Vendedor',
        required=True,
        readonly=True,
    )

    authorizer_id = fields.Many2one(
        'res.users',
        string='Autorizado por',
    )

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('pending', 'Pendiente'),
        ('approved', 'Aprobado'),
        ('rejected', 'Rechazado'),
        ('expired', 'Expirado'),
    ], string='Estado', default='pending', required=True, tracking=True)

    operation_type = fields.Selection([
        ('hold', 'Apartado'),
        ('sale', 'Venta'),
    ], string='Tipo de Operación', required=True)

    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        tracking=True,
    )

    project_id = fields.Many2one(
        'project.project',
        string='Proyecto',
        tracking=True,
    )

    currency_code = fields.Selection([
        ('USD', 'USD'),
        ('MXN', 'MXN'),
    ], string='Divisa', required=True)

    line_ids = fields.One2many(
        'price.authorization.line',
        'authorization_id',
        string='Productos',
    )

    notes = fields.Text(
        string='Notas del Vendedor',
    )

    authorization_notes = fields.Text(
        string='Notas del Autorizador',
    )

    create_date = fields.Datetime(
        string='Fecha Solicitud',
        readonly=True,
    )

    authorization_date = fields.Datetime(
        string='Fecha Autorización',
        readonly=True,
        tracking=True,
    )

    temp_data = fields.Json(
        string='Datos Temporales',
    )

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Orden de Venta Generada',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = self.env['ir.sequence'].next_by_code('price.authorization') or 'Nuevo'

            vals['state'] = 'pending'

        records = super().create(vals_list)

        for record in records:
            record._notify_authorizers()

        return records

    def _notify_authorizers(self):
        """Notifica a todos los usuarios autorizadores sobre la nueva solicitud"""
        self.ensure_one()

        authorizer_group = self.env.ref('inventory_shopping_cart.group_price_authorizer')
        authorizers = authorizer_group.user_ids.filtered(lambda u: u.id != self.seller_id.id)

        if not authorizers:
            return

        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([('name', '=', 'To Do')], limit=1)

        for authorizer in authorizers:
            self.activity_schedule(
                activity_type_id=activity_type.id,
                summary=f'Autorización {self.name}',
                note=f"""
                    <p>Se requiere su autorización para:</p>
                    <ul>
                        <li><strong>Vendedor:</strong> {self.seller_id.name}</li>
                        <li><strong>Cliente:</strong> {self.partner_id.name}</li>
                        <li><strong>Operación:</strong> {'Venta' if self.operation_type == 'sale' else 'Apartado'}</li>
                        <li><strong>Productos:</strong> {len(self.line_ids)} productos</li>
                    </ul>
                """,
                user_id=authorizer.id,
            )

    def _notify_seller(self, approved=True):
        """Notifica al vendedor sobre la decisión"""
        self.ensure_one()

        if approved:
            activity_summary = f'Autorización Aprobada - {self.name}'
            message_text = f"<p>Su solicitud {self.name} ha sido <strong>aprobada</strong> por {self.authorizer_id.name}.</p>"

            if self.operation_type == 'sale' and self.sale_order_id:
                message_text += (
                    f"<p>La orden <a href='/web#id={self.sale_order_id.id}&model=sale.order&view_type=form'>"
                    f"{self.sale_order_id.name}</a> ha sido actualizada con los precios autorizados.</p>"
                    f"<p><strong>Ya puede confirmar la orden.</strong></p>"
                )
            elif self.operation_type == 'hold':
                message_text += "<p>Los apartados han sido creados automáticamente.</p>"
        else:
            activity_summary = f'Autorización Rechazada - {self.name}'
            message_text = f"<p>Su solicitud {self.name} ha sido <strong>rechazada</strong> por {self.authorizer_id.name}.</p>"

        if self.authorization_notes:
            message_text += f"<p><strong>Comentarios:</strong><br/>{self.authorization_notes}</p>"

        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([('name', '=', 'To Do')], limit=1)

        self.activity_schedule(
            activity_type_id=activity_type.id,
            summary=activity_summary,
            note=message_text,
            user_id=self.seller_id.id,
        )

    def action_approve(self):
        self.ensure_one()

        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("No tiene permisos para autorizar precios")

        self.activity_ids.filtered(lambda a: a.user_id == self.env.user).action_done()

        self.write({
            'state': 'approved',
            'authorizer_id': self.env.user.id,
            'authorization_date': fields.Datetime.now(),
        })

        self._process_approved_authorization()
        self._notify_seller(approved=True)

    def action_reject(self):
        self.ensure_one()

        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("No tiene permisos para rechazar precios")

        self.activity_ids.filtered(lambda a: a.user_id == self.env.user).action_done()

        self.write({
            'state': 'rejected',
            'authorizer_id': self.env.user.id,
            'authorization_date': fields.Datetime.now(),
        })

        self._notify_seller(approved=False)

    def _process_approved_authorization(self):
        """
        Procesa la autorización aprobada.

        - Para ventas desde orden manual: solo actualiza precios.
        - Para ventas desde carrito: crea y confirma orden.
        - Para holds: crea apartados respetando cantidades parciales.
        """
        self.ensure_one()

        if not self.temp_data:
            raise UserError("No hay datos temporales para procesar")

        temp_data = self.temp_data

        pricelist = self.env['product.pricelist'].search([
            ('name', '=', self.currency_code)
        ], limit=1)

        if not pricelist:
            raise UserError(f"No se encontró lista de precios para {self.currency_code}")

        if self.operation_type == 'sale':
            source = temp_data.get('source', '')
            existing_order_id = temp_data.get('sale_order_id') or (
                self.sale_order_id.id if self.sale_order_id else False
            )

            if source == 'manual_order' and existing_order_id:
                self._update_existing_order_prices(existing_order_id)
            else:
                self._create_sale_order_from_authorization(pricelist, temp_data)

        elif self.operation_type == 'hold':
            if temp_data.get('source') == 'manual_hold_order':
                self._confirm_existing_hold_order_from_authorization(temp_data)
            else:
                self._create_holds_from_authorization(temp_data)

    def _update_existing_order_prices(self, order_id):
        """
        Cuando la autorización viene de una orden manual existente:
        solo actualiza precios, no confirma la orden.
        """
        order = self.env['sale.order'].browse(order_id)

        if not order.exists():
            raise UserError(f"La orden de venta ID {order_id} ya no existe.")

        if order.state not in ['draft', 'sent']:
            raise UserError(f"La orden {order.name} ya no está en estado borrador.")

        for line in self.line_ids:
            order_lines = order.order_line.filtered(
                lambda l: l.product_id.id == line.product_id.id and not l.display_type
            )

            for order_line in order_lines:
                order_line.write({
                    'price_unit': math.ceil(line.authorized_price),
                    'x_price_selector': 'custom',
                })

        order.x_price_authorization_id = self.id
        self.write({'sale_order_id': order.id})

    def _create_sale_order_from_authorization(self, pricelist, temp_data):
        """
        Crea orden de venta desde autorización aprobada del carrito.
        Usa authorized_price redondeado hacia arriba.
        """
        product_prices = {}

        for line in self.line_ids:
            product_prices[str(line.product_id.id)] = math.ceil(line.authorized_price)

        products = []
        product_groups = temp_data.get('product_groups', {})

        for product_id_str, group in product_groups.items():
            products.append({
                'product_id': int(product_id_str),
                'quantity': group['total_quantity'],
                'price_unit': float(product_prices.get(product_id_str, 0)),
                'selected_lots': [lot['id'] for lot in group['lots']],
                'lots_breakdown': {
                    str(lot['id']): float(lot.get('quantity') or 0.0)
                    for lot in group['lots']
                    if lot.get('quantity')
                },
                'to_be_purchased': bool(group.get('to_be_purchased')),
            })

        services = temp_data.get('services', [])

        notes = self.notes or ''
        apply_tax = temp_data.get('apply_tax', True)

        company_id = self.env.context.get('company_id') or self.env.company.id

        for product in products:
            for quant_id in product['selected_lots']:
                quant = self.env['stock.quant'].browse(quant_id)
                if quant.x_tiene_hold:
                    hold_partner = quant.x_hold_activo_id.partner_id
                    if hold_partner.id != self.partner_id.id:
                        raise UserError(
                            f"El lote {quant.lot_id.name} está apartado para {hold_partner.name}"
                        )

        addr = self.partner_id.address_get(['delivery', 'invoice'])
        invoice_id = addr.get('invoice', self.partner_id.id)
        shipping_id = addr.get('delivery', self.partner_id.id)

        sale_order = self.env['sale.order'].with_company(company_id).sudo().create({
            'partner_id': self.partner_id.id,
            'partner_invoice_id': invoice_id,
            'partner_shipping_id': shipping_id,
            'user_id': self.seller_id.id,
            'note': notes,
            'pricelist_id': pricelist.id,
            'company_id': company_id,
            'x_price_authorization_id': self.id,
            'x_project_id': self.project_id.id if self.project_id else False,
            'x_architect_id': temp_data.get('architect_id') or False,
        })

        for product in products:
            product_rec = self.env['product.product'].browse(product['product_id'])

            if apply_tax and product_rec.taxes_id:
                tax_ids = [(6, 0, product_rec.taxes_id.ids)]
            else:
                tax_ids = [(5, 0, 0)]

            line_vals = {
                'order_id': sale_order.id,
                'product_id': product['product_id'],
                'product_uom_qty': product['quantity'],
                'price_unit': product['price_unit'],
                'tax_ids': tax_ids,
                'x_selected_lots': [(6, 0, product['selected_lots'])],
                'x_lot_breakdown_json': product.get('lots_breakdown') or {},
                'x_price_selector': 'custom',
                'company_id': company_id,
            }

            # Material sin existencia ("mandar a pedir"); el campo solo existe
            # si stock_transit_allocation está instalado.
            if product.get('to_be_purchased') and 'auto_transit_assign' in self.env['sale.order.line']._fields:
                line_vals['auto_transit_assign'] = True

            self.env['sale.order.line'].with_company(company_id).sudo().create(line_vals)

        if services:
            for service in services:
                service_product = self.env['product.product'].browse(service['product_id'])

                if apply_tax and service_product.taxes_id:
                    tax_ids = [(6, 0, service_product.taxes_id.ids)]
                else:
                    tax_ids = [(5, 0, 0)]

                self.env['sale.order.line'].with_company(company_id).sudo().create({
                    'order_id': sale_order.id,
                    'product_id': service['product_id'],
                    'product_uom_qty': service['quantity'],
                    'price_unit': math.ceil(service['price_unit']),
                    'tax_ids': tax_ids,
                    'company_id': company_id,
                })

        sale_order._sync_lot_ids_from_selected_lots()
        sale_order.with_company(company_id).with_context(skip_auth_check=True).sudo().action_confirm()

        for line in sale_order.order_line:
            if line.x_selected_lots:
                picking = line.move_ids.mapped('picking_id')
                if picking:
                    self.env['sale.order'].sudo()._assign_specific_lots(
                        picking,
                        line.product_id,
                        line.x_selected_lots,
                    )

        self.write({'sale_order_id': sale_order.id})

    def _create_holds_from_authorization(self, temp_data):
        """
        Crea apartados desde autorización aprobada.

        Corrección:
        - Conserva selected_quantities para respetar cantidades parciales de formatos/piezas.
        - Usa los precios autorizados.
        """
        product_prices = {}

        for line in self.line_ids:
            product_prices[str(line.product_id.id)] = math.ceil(line.authorized_price)

        selected_lots = temp_data.get('selected_lots', [])
        selected_quantities = temp_data.get('selected_quantities') or {}
        architect_id = temp_data.get('architect_id')
        services = temp_data.get('services') or []
        backorder_items = temp_data.get('backorder_items') or []

        full_notes = self.notes or ''

        result = self.env['stock.quant'].with_context(
            skip_authorization_check=True,
            force_seller_id=self.seller_id.id,
        ).create_holds_from_cart(
            partner_id=self.partner_id.id,
            project_id=self.project_id.id if self.project_id else None,
            architect_id=architect_id,
            selected_lots=selected_lots,
            selected_quantities=selected_quantities,
            notes=full_notes,
            currency_code=self.currency_code,
            product_prices=product_prices,
            services=services,
            backorder_items=backorder_items,
        )

        if result.get('success', 0) == 0 and result.get('errors', 0) > 0:
            error_msg = "Errores al crear apartados:\n"
            for failed in result.get('failed', []):
                error_msg += f"• {failed.get('lot_name', 'Lote')}: {failed.get('error', 'Error desconocido')}\n"
            raise UserError(error_msg)

    def _confirm_existing_hold_order_from_authorization(self, temp_data):
        """
        Aplica una autorización aprobada sobre un apartado manual existente.

        No crea un nuevo apartado: actualiza los precios autorizados en la orden
        de reserva en borrador y después la confirma saltando la validación de
        autorización para evitar un ciclo infinito.
        """
        self.ensure_one()

        hold_order_id = temp_data.get('hold_order_id')
        if not hold_order_id:
            raise UserError("La autorización no tiene una orden de apartado vinculada.")

        order = self.env['stock.lot.hold.order'].browse(int(hold_order_id))
        if not order.exists():
            raise UserError(f"La orden de apartado ID {hold_order_id} ya no existe.")

        if order.state not in ['draft', 'borrador']:
            raise UserError(f"La orden de apartado {order.name} ya no está en borrador.")

        product_prices = {
            line.product_id.id: math.ceil(line.authorized_price)
            for line in self.line_ids
        }

        order_lines = self.env['stock.lot.hold.order.line']
        if hasattr(order, 'line_ids'):
            order_lines |= order.line_ids
        if hasattr(order, 'hold_line_ids'):
            order_lines |= order.hold_line_ids

        for order_line in order_lines:
            if not order_line.product_id or order_line.product_id.type == 'service':
                continue

            authorized_price = product_prices.get(order_line.product_id.id)
            if authorized_price is False or authorized_price is None:
                continue

            vals = {
                'precio_unitario': authorized_price,
            }
            if hasattr(order_line, 'x_price_selector'):
                vals['x_price_selector'] = 'custom'

            order_line.write(vals)

        order.message_post(
            body=(
                f"Autorización de precio {self.name} aprobada por "
                f"{self.authorizer_id.name}. Se aplicaron los precios autorizados."
            )
        )

        order.with_context(skip_authorization_check=True).action_confirm()



class PriceAuthorizationLine(models.Model):
    _name = 'price.authorization.line'
    _description = 'Línea de Autorización de Precio'

    authorization_id = fields.Many2one(
        'price.authorization',
        string='Autorización',
        required=True,
        ondelete='cascade',
    )

    product_id = fields.Many2one(
        'product.product',
        string='Producto',
        required=True,
    )

    quantity = fields.Float(
        string='Cantidad m²',
        required=True,
    )

    lot_count = fields.Integer(
        string='# Lotes',
        required=True,
    )

    requested_price = fields.Float(
        string='Precio Solicitado',
        required=True,
        digits='Product Price',
    )

    medium_price = fields.Float(
        string='Precio 2 (Medio)',
        readonly=True,
        digits='Product Price',
    )

    minimum_price = fields.Float(
        string='Precio 3',
        readonly=True,
        digits='Product Price',
    )

    level_4_price = fields.Float(
        string='Precio 4',
        readonly=True,
        digits='Product Price',
    )

    level_5_price = fields.Float(
        string='Precio 5 (Mínimo)',
        readonly=True,
        digits='Product Price',
    )

    authorized_price = fields.Float(
        string='Precio Autorizado',
        required=True,
        digits='Product Price',
        help='Precio final autorizado. Puede ser diferente al solicitado.',
    )

    price_level = fields.Selection([
        ('below_minimum', 'Debajo del Mínimo'),
        ('minimum', 'Precio Mínimo'),
        ('below_medium', 'Entre Mínimo y Medio'),
    ], string='Nivel de Precio', compute='_compute_price_level', store=True)

    product_cost = fields.Float(
        string='Costo Destino',
        related='product_id.product_tmpl_id.x_costo_mayor',
        readonly=True,
        digits='Product Price',
    )

    @api.depends('requested_price', 'minimum_price', 'medium_price')
    def _compute_price_level(self):
        for line in self:
            if line.requested_price < line.minimum_price:
                line.price_level = 'below_minimum'
            elif line.requested_price == line.minimum_price:
                line.price_level = 'minimum'
            else:
                line.price_level = 'below_medium'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'requested_price' in vals:
                vals['requested_price'] = math.ceil(vals['requested_price'])

            if 'authorized_price' not in vals and 'requested_price' in vals:
                vals['authorized_price'] = vals['requested_price']
            elif 'authorized_price' in vals:
                vals['authorized_price'] = math.ceil(vals['authorized_price'])

            for level_field in ('medium_price', 'minimum_price', 'level_4_price', 'level_5_price'):
                if level_field in vals and vals[level_field] is not None:
                    vals[level_field] = math.ceil(vals[level_field])

        return super().create(vals_list)

    def write(self, vals):
        if 'requested_price' in vals:
            vals['requested_price'] = math.ceil(vals['requested_price'])

        if 'authorized_price' in vals:
            vals['authorized_price'] = math.ceil(vals['authorized_price'])

        for level_field in ('medium_price', 'minimum_price', 'level_4_price', 'level_5_price'):
            if level_field in vals and vals[level_field] is not None:
                vals[level_field] = math.ceil(vals[level_field])

        return super().write(vals)