# -*- coding: utf-8 -*-
import json
import logging
import math

from markupsafe import Markup

from odoo import models, fields, api
from odoo.addons.inventory_shopping_cart.models.som_date_format import som_format_date
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


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

    # ── CANDADO DE DUPLICADOS (2 sep 2026): una solicitud IDÉNTICA (misma
    # operación, cliente, proyecto, orden, divisa y los mismos productos con
    # cantidad y precio) a una que sigue PENDIENTE no se vuelve a crear ni
    # a notificar: se reutiliza la pendiente. La firma se guarda para
    # buscarla con un índice, no comparando líneas. ──
    som_request_signature = fields.Char(
        string='Firma de la solicitud', index=True, readonly=True, copy=False)
    som_duplicate_notice = fields.Char(
        string='Aviso de duplicado', store=False, readonly=True,
        help='Solo en memoria: mensaje para el vendedor cuando su solicitud se '
             'reutilizó en vez de crear otra.')
    som_resend_count = fields.Integer(
        string='Reenvíos evitados', default=0, readonly=True, copy=False,
        help='Veces que el vendedor volvió a mandar esta misma solicitud '
             'mientras seguía pendiente (no se creó ni notificó ninguna).')

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Orden de Venta Generada',
        readonly=True,
    )

    # Multiempresa: compañía del documento. La toma de la orden generada
    # (sale_order_id) cuando existe; si no, la que mande el flujo que la
    # crea (carrito/apartado) o la compañía activa del usuario.
    company_id = fields.Many2one(
        'res.company', string='Compañía',
        compute='_compute_company_id', store=True, readonly=False,
        precompute=True, index=True,
    )

    @api.depends('sale_order_id', 'sale_order_id.company_id')
    def _compute_company_id(self):
        for rec in self:
            rec.company_id = (
                rec.sale_order_id.company_id
                or rec.company_id
                or self.env.company
            )

    @api.model
    def _som_company_from_vals(self, vals):
        """Compañía del documento ANTES de pedir el folio."""
        if vals.get('company_id'):
            return self.env['res.company'].browse(vals['company_id'])
        if vals.get('sale_order_id'):
            order = self.env['sale.order'].browse(vals['sale_order_id']).exists()
            if order and order.company_id:
                return order.company_id
        return self.env.company

    @api.model
    def _som_request_signature(self, vals):
        """Firma determinista de la solicitud a partir de lo que TODOS los
        flujos mandan en temp_data (product_groups con total_quantity y
        product_prices). Sin precios o sin productos no hay firma (y no se
        deduplica: ante la duda, se crea)."""
        td = vals.get('temp_data') or {}
        if not isinstance(td, dict):
            return False
        groups = td.get('product_groups') or {}
        prices = td.get('product_prices') or {}
        if not groups or not prices:
            return False
        items = []
        for pid, group in groups.items():
            qty = float((group or {}).get('total_quantity') or 0.0)
            price = prices.get(str(pid), prices.get(pid))
            if price is None:
                return False
            items.append([str(pid), round(qty, 4), round(float(price or 0.0), 4)])
        items.sort()
        return json.dumps({
            'op': vals.get('operation_type') or '',
            'partner': vals.get('partner_id') or False,
            'project': vals.get('project_id') or False,
            'order': vals.get('sale_order_id') or False,
            'hold': td.get('hold_order_id') or False,
            'cur': vals.get('currency_code') or '',
            'items': items,
        }, sort_keys=True)

    @api.model
    def _som_reused_ids(self):
        # cr.cache vive toda la transacción (precommit.data se vacía en cada
        # flush y perdería la marca entre la cabecera y sus líneas).
        return self.env.cr.cache.setdefault('som_price_auth_reused', set())

    def _som_mark_resent(self, vals):
        """La solicitud pendiente se reutiliza: aviso al vendedor (en memoria
        y en el chatter de la orden/apartado), rastro en la propia solicitud
        y NINGUNA notificación nueva a los autorizadores."""
        self.ensure_one()
        self._som_reused_ids().add(self.id)
        notice = (
            'Ya existe la solicitud %s pendiente con exactamente estos productos, '
            'cantidades y precios. No se envió otra: el autorizador sigue viendo la misma.'
        ) % self.name
        self.sudo().write({'som_resend_count': (self.som_resend_count or 0) + 1})
        self.som_duplicate_notice = notice
        body = Markup('<p>Reenvío idéntico del vendedor %s: no se creó otra solicitud ni se volvió a avisar '
                      '(reenvíos evitados: %d).</p>') % (self.env.user.name, self.som_resend_count)
        try:
            self.sudo().message_post(body=body, message_type='notification')
        except Exception:  # noqa: BLE001
            pass
        order_id = vals.get('sale_order_id')
        if order_id:
            try:
                self.env['sale.order'].sudo().browse(order_id).message_post(
                    body=Markup('<p>%s</p>') % notice, message_type='notification')
            except Exception:  # noqa: BLE001
                pass
        _logger.info('[PRICE AUTH] %s reenviada idéntica por %s: reutilizada (sin nueva notificación)',
                     self.name, self.env.user.name)
        return notice

    @api.model_create_multi
    def create(self, vals_list):
        reused = self.browse()
        to_create = []
        for vals in vals_list:
            company = self._som_company_from_vals(vals)
            if not vals.get('company_id'):
                vals['company_id'] = company.id

            # CANDADO: misma solicitud pendiente → se reutiliza, no se crea.
            signature = self._som_request_signature(vals)
            vals['som_request_signature'] = signature or False
            if signature:
                dup = self.sudo().search([
                    ('state', '=', 'pending'),
                    ('company_id', '=', company.id),
                    ('som_request_signature', '=', signature),
                ], order='id desc', limit=1)
                if dup:
                    dup = dup.with_env(self.env)
                    dup._som_mark_resent(vals)
                    reused |= dup
                    continue

            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = self.env['sale.order']._som_next_sequence(
                    'price.authorization', company) or 'Nuevo'

            vals['state'] = 'pending'
            to_create.append(vals)

        records = super().create(to_create) if to_create else self.browse()

        for record in records:
            record._notify_authorizers()

        return records | reused

    @api.model
    def _som_authorizer_users(self):
        """Autorizadores de precios mínimos, tolerante a Odoo 19.

        `group.user_ids` solo trae a quienes tienen el grupo DIRECTO; los
        que lo reciben por IMPLICACIÓN de otro grupo viven en `all_user_ids`
        — leer solo user_ids dejaba autorizadores sin notificar (o a todos,
        si nadie lo tenía directo) en TODAS las apps comerciales.
        """
        Users = self.env['res.users']
        group = self.env.ref(
            'inventory_shopping_cart.group_price_authorizer',
            raise_if_not_found=False)
        if not group:
            return Users

        users = Users
        for fname in ('all_user_ids', 'user_ids', 'users'):
            if fname in group._fields:
                users |= group[fname]

        if not users:
            for fname in ('all_group_ids', 'group_ids', 'groups_id'):
                if fname in Users._fields:
                    users = Users.search([(fname, 'in', group.id)])
                    break

        return users.filtered(lambda u: u.active and not u.share)

    def _notify_authorizers(self):
        """Notifica a TODOS los autorizadores la nueva solicitud: actividad
        (systray) + mención en el chatter (inbox/correo). Este es el punto
        único por el que pasan todas las apps comerciales (carrito, quote,
        orden manual, holds): toda solicitud nace en create()."""
        self.ensure_one()

        authorizers = self._som_authorizer_users().filtered(
            lambda u: u.id != self.seller_id.id)

        if not authorizers:
            _logger.warning(
                "[PRICE AUTH] %s creada SIN autorizadores a quien notificar "
                "(grupo Autorizador de Precios Mínimos vacío o solo el "
                "propio vendedor).", self.name)
            return

        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([('name', '=', 'To Do')], limit=1)

        reason = html2plaintext(self.notes or '').strip() if self.notes else ''
        note = (
            f"<p>Se requiere su autorización para:</p>"
            f"<ul>"
            f"<li><strong>Vendedor:</strong> {self.seller_id.name}</li>"
            f"<li><strong>Cliente:</strong> {self.partner_id.name}</li>"
            f"<li><strong>Operación:</strong> {'Venta' if self.operation_type == 'sale' else 'Apartado'}</li>"
            f"<li><strong>Productos:</strong> {len(self.line_ids)} productos</li>"
            f"</ul>"
            + (f"<p><strong>Justificación del vendedor:</strong> {Markup.escape(reason)}</p>" if reason else
               "<p><em>Sin justificación capturada.</em></p>")
        )

        # UNA actividad por autorizador + mención en chatter. Las
        # actividades se CIERRAN SOLAS al aprobar/rechazar (todas, no solo
        # la del que decidió) vía _som_close_open_activities — así el reloj
        # del systray avisa de verdad y no acumula pendientes falsos.
        for authorizer in authorizers:
            try:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=f'Autorizar precios · {self.name}',
                    note=note,
                    user_id=authorizer.id,
                )
            except Exception:
                _logger.exception(
                    '[PRICE AUTH] No se pudo agendar la actividad de %s '
                    'para %s.', self.name, authorizer.name)

        self.message_post(
            body=Markup(
                '<p><b>🔐 Autorización de precios mínimos requerida: %s</b></p>%s'
            ) % (self.name, Markup(note)),
            partner_ids=authorizers.partner_id.ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def _som_close_open_activities(self, feedback):
        """Cierra TODAS las actividades abiertas de la solicitud — las de
        todos los autorizadores, no solo la del usuario que decidió (antes
        cada quien cerraba la suya y las demás quedaban colgadas)."""
        for rec in self:
            activities = rec.sudo().activity_ids
            if not activities:
                continue
            try:
                activities.action_feedback(feedback=feedback)
            except Exception:
                _logger.exception(
                    '[PRICE AUTH] No se pudieron cerrar las actividades '
                    'de %s.', rec.name)

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

        # Mención de chatter, NO actividad: el resultado es un aviso que el
        # vendedor lee, no una tarea que alguien cierre. Como actividad se
        # quedaba abierta para siempre — y encima se sumaba a la del
        # autorizador, que tampoco se cerraba. Así llega igual por inbox y
        # correo, y el reloj queda limpio.
        if self.seller_id.partner_id:
            self.message_post(
                body=Markup('<p><b>%s</b></p>%s') % (
                    activity_summary, Markup(message_text)),
                partner_ids=self.seller_id.partner_id.ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    # ------------------------------------------------------------------
    # ORDEN/COTIZACIÓN VINCULADA
    # ------------------------------------------------------------------
    x_linked_order_id = fields.Many2one(
        'sale.order',
        string='Orden/Cotización Vinculada',
        compute='_compute_x_linked_order_id',
        help='La orden generada (sale_order_id) o, en su defecto, la '
             'cotización de origen registrada en temp_data.',
    )

    @api.depends('sale_order_id', 'temp_data')
    def _compute_x_linked_order_id(self):
        Order = self.env['sale.order']
        for rec in self:
            order = rec.sale_order_id
            if not order:
                data = rec.temp_data or {}
                order_id = data.get('sale_order_id')
                if order_id:
                    order = Order.browse(int(order_id)).exists()
            rec.x_linked_order_id = order or False

    def action_view_linked_order(self):
        """Abrir la orden/cotización ligada directamente en su formulario
        (funciona igual para cotizaciones que para órdenes confirmadas)."""
        self.ensure_one()
        order = self.x_linked_order_id
        if not order:
            raise UserError('Esta solicitud no tiene una orden o cotización vinculada.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # INTERFAZ DE REVISIÓN (widget OWL price_auth_review)
    # ------------------------------------------------------------------
    def get_review_data(self):
        """Datos para la interfaz visual de revisión: por producto los 3
        niveles de precio (P1/P2/P3) y el TOTAL de la operación — sin
        detalle de lotes. Los niveles y el costo solo viajan al autorizador."""
        self.ensure_one()
        Product = self.env['product.template']
        is_authorizer = self.env.user.has_group(
            'inventory_shopping_cart.group_price_authorizer')
        currency = self.currency_code or 'USD'
        # Multiempresa: TC y escalera/costos (company_dependent) de la
        # compañía del documento, no de la activa del usuario.
        company = self.company_id or self.env.company

        # Tipo de cambio del día para mostrar cada nivel/costo en AMBAS
        # divisas (derivado cuando solo está capturado en una).
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        mxn = self.env.ref('base.MXN', raise_if_not_found=False)
        rate = 0.0
        if usd and mxn:
            try:
                rate = usd._convert(1.0, mxn, company, fields.Date.context_today(self)) or 0.0
            except Exception:  # noqa: BLE001
                rate = 0.0

        def _pair(usd_val, mxn_val):
            """{usd, mxn, usd_derived, mxn_derived}: completa la divisa faltante."""
            usd_val = float(usd_val or 0.0)
            mxn_val = float(mxn_val or 0.0)
            out = {'usd': usd_val, 'mxn': mxn_val, 'usd_derived': False, 'mxn_derived': False}
            if rate:
                if not mxn_val and usd_val:
                    out['mxn'] = usd_val * rate
                    out['mxn_derived'] = True
                if not usd_val and mxn_val:
                    out['usd'] = mxn_val / rate
                    out['usd_derived'] = True
            return out

        def _to_both(value, code):
            value = float(value or 0.0)
            if code == 'MXN':
                return {'usd': (value / rate) if rate else 0.0, 'mxn': value,
                        'usd_derived': True, 'mxn_derived': False}
            return {'usd': value, 'mxn': value * rate if rate else 0.0,
                    'usd_derived': False, 'mxn_derived': True}

        def _margin(price_usd, cost_usd):
            if price_usd and cost_usd:
                return round((price_usd - cost_usd) / price_usd * 100.0, 1)
            return None

        lines = []
        total_requested = 0.0
        total_authorized = 0.0
        total_qty = 0.0
        for line in self.line_ids:
            tmpl = (
                line.product_id.product_tmpl_id.with_company(company)
                if line.product_id else False
            )
            qty = line.quantity or 0.0
            req = line.requested_price or 0.0
            auth = line.authorized_price or req
            total_requested += qty * req
            total_authorized += qty * auth
            total_qty += qty
            item = {
                'id': line.id,
                'product': line.product_id.display_name or '',
                'quantity': qty,
                'uom': (line.product_id.uom_id.name if line.product_id else '') or 'm²',
                'requested_price': req,
                'authorized_price': line.authorized_price or 0.0,
                'price_level': line.price_level or '',
                'subtotal': qty * auth,
            }
            if is_authorizer:
                # Costos en DÓLARES para el autorizador: base (standard_price
                # expresado en USD) y ALL-IN USD cuando el motor de costeo ya
                # lo calculó (>0). Solo viajan al autorizador.
                cost_base_usd = 0.0
                cost_allin_usd = 0.0
                if tmpl:
                    cost_base_usd = getattr(tmpl, 'x_costo_usd_edit', 0.0) or 0.0
                    cost_allin_usd = getattr(tmpl, 'x_costo_mayor_usd', 0.0) or 0.0
                item.update({
                    'price_1': Product._get_price_level_value(tmpl, 'high', currency) if tmpl else 0.0,
                    'price_2': line.medium_price or 0.0,
                    'price_3': line.minimum_price or 0.0,
                    'cost': line.product_cost or 0.0,
                    'cost_base_usd': cost_base_usd,
                    'cost_allin_usd': cost_allin_usd,
                })
                # Matriz completa en USD y MXN: 5 niveles + costos + prometido/autorizado.
                if tmpl:
                    allin = _pair(getattr(tmpl, 'x_costo_mayor_usd', 0.0), getattr(tmpl, 'x_costo_mayor', 0.0))
                    base = _pair(getattr(tmpl, 'x_costo_usd_edit', 0.0), getattr(tmpl, 'x_costo_mxn_edit', 0.0))
                    levels = []
                    for n in range(1, 6):
                        pr = _pair(getattr(tmpl, 'x_price_usd_%d' % n, 0.0), getattr(tmpl, 'x_price_mxn_%d' % n, 0.0))
                        pr.update({'key': str(n), 'label': 'Precio %d' % n,
                                   'margin': _margin(pr['usd'], allin['usd'])})
                        levels.append(pr)
                    req_pair = _to_both(req, currency)
                    auth_pair = _to_both(auth, currency)
                    item['matrix'] = {
                        'rate': rate,
                        'levels': levels,
                        'costs': [
                            dict(base, label='Costo base'),
                            dict(allin, label='Costo ALL-IN'),
                        ],
                        'requested': dict(req_pair, label='Prometido', margin=_margin(req_pair['usd'], allin['usd'])),
                        'authorized': dict(auth_pair, label='Autorizado', margin=_margin(auth_pair['usd'], allin['usd'])),
                    }
            lines.append(item)

        def _dt(value):
            if not value:
                return ''
            return som_format_date(
                fields.Datetime.context_timestamp(self, value),
                empty='', with_time=True)

        return {
            'id': self.id,
            'name': self.name or '',
            'state': self.state,
            'state_label': dict(self._fields['state'].selection).get(self.state, self.state),
            'operation_label': dict(self._fields['operation_type'].selection).get(self.operation_type, ''),
            'partner': self.partner_id.display_name or '',
            'project': self.project_id.display_name or '',
            'seller': self.seller_id.name or '',
            'authorizer': self.authorizer_id.name or '',
            'currency': currency,
            'usd_rate': rate,
            'create_date': _dt(self.create_date),
            'authorization_date': _dt(self.authorization_date),
            'sale_order': self.sale_order_id.name or '',
            # Notas pueden traer HTML heredado (note de la OV): a texto plano.
            'notes': html2plaintext(self.notes) if self.notes else '',
            'is_authorizer': is_authorizer,
            'can_authorize': is_authorizer and self.state == 'pending',
            'lines': lines,
            'totals': {
                'qty': total_qty,
                'requested': total_requested,
                'authorized': total_authorized,
            },
        }

    def set_line_authorized_price(self, line_id, price):
        """Ajuste del precio autorizado desde la interfaz de revisión."""
        self.ensure_one()
        if self.state != 'pending':
            raise UserError('Solo se puede ajustar el precio en una solicitud pendiente.')
        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError('No tiene permisos para ajustar el precio autorizado.')
        line = self.line_ids.filtered(lambda l: l.id == int(line_id))
        if line:
            line.write({'authorized_price': float(price or 0.0)})
        return True

    def action_approve(self):
        self.ensure_one()

        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("No tiene permisos para autorizar precios")

        self._som_close_open_activities(
            f'Aprobada por {self.env.user.name}')

        self.write({
            'state': 'approved',
            'authorizer_id': self.env.user.id,
            'authorization_date': fields.Datetime.now(),
        })

        self._process_approved_authorization()
        self._som_write_authorized_floors()
        self._notify_seller(approved=True)

    def _som_write_authorized_floors(self):
        """Graba en la orden el piso autorizado por producto. Bajar de ese
        piso después re-bloquea la orden aunque la autorización siga
        aprobada (sale.order._compute_has_low_prices)."""
        self.ensure_one()
        order = self.sale_order_id
        if not order:
            return
        floors = dict(order.x_authorized_floor_json or {})
        for line in self.line_ids:
            if line.product_id and line.authorized_price:
                floors[str(line.product_id.id)] = math.ceil(line.authorized_price)
        if floors:
            order.x_authorized_floor_json = floors

    def action_reject(self):
        self.ensure_one()

        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("No tiene permisos para rechazar precios")

        self._som_close_open_activities(
            f'Rechazada por {self.env.user.name}')

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

        # Lista de precios compartida o de la compañía del documento.
        company = self.company_id or self.env.company
        pricelist = self.env['product.pricelist'].search([
            ('name', '=', self.currency_code),
            ('company_id', 'in', [company.id, False]),
        ], order='company_id', limit=1)

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

        if order.state not in ['draft', 'sent', 'sale']:
            raise UserError(
                f"La orden {order.name} está cancelada o bloqueada; "
                f"no se pueden aplicar los precios autorizados."
            )

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

        # Orden manual que NACIÓ confirmada pero quedó en borrador esperando
        # esta autorización (sale_menu_restructure): con la aprobación se
        # confirma sola. Si algo más la bloquea (lotes tomados, etc.), la
        # aprobación NO truena — queda constancia y se confirma a mano.
        if (
            getattr(order, 'x_born_confirmed', False)
            and order.state == 'draft'
            and hasattr(order, '_born_confirm_if_ready')
        ):
            try:
                order.with_context(
                    skip_sale_order_redirect=True)._born_confirm_if_ready()
            except Exception:
                _logger.exception(
                    '[PRICE AUTH] %s aprobada pero la orden %s no se pudo '
                    'confirmar automáticamente.', self.name, order.name)
                order._message_log(body=Markup(
                    '<p>⚠️ Autorización aprobada, pero la orden no se pudo '
                    'confirmar automáticamente; confírmela manualmente.</p>'))

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

        # Compañía del documento (la de la solicitud, que nació de la del
        # material); el contexto solo la sobreescribe explícitamente.
        company_id = (
            self.env.context.get('company_id')
            or self.company_id.id
            or self.env.company.id
        )

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
            # El apartado nace en la compañía de la solicitud.
            som_force_company_id=self.company_id.id or False,
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

        # El apartado creado queda ligado a esta autorización: al convertirlo
        # a orden de venta, la orden la hereda y no la vuelve a pedir.
        if result.get('order_id'):
            hold = self.env['stock.lot.hold.order'].browse(result['order_id']).exists()
            if hold and 'x_price_authorization_id' in hold._fields:
                hold.sudo().write({'x_price_authorization_id': self.id})

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
        if 'x_price_authorization_id' in order._fields:
            order.x_price_authorization_id = self.id

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

    company_id = fields.Many2one(
        'res.company', string='Compañía',
        related='authorization_id.company_id',
        store=True, readonly=True, index=True,
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

    # x_costo_mayor es company_dependent: se lee con la compañía de la
    # solicitud (un related lo leería con la compañía activa del usuario).
    product_cost = fields.Float(
        string='Costo Destino',
        compute='_compute_product_cost',
        readonly=True,
        digits='Product Price',
    )

    @api.depends('product_id', 'company_id')
    def _compute_product_cost(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if tmpl:
                company = line.company_id or self.env.company
                line.product_cost = tmpl.with_company(company).x_costo_mayor or 0.0
            else:
                line.product_cost = 0.0

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

        # Solicitud REUTILIZADA (reenvío idéntico): los flujos crean sus
        # líneas después de la cabecera; aquí se devuelve la línea que ya
        # existe para ese producto en vez de duplicarla.
        reused = self.env['price.authorization']._som_reused_ids()
        if reused:
            result = self.browse()
            fresh = []
            for vals in vals_list:
                auth_id = vals.get('authorization_id')
                if auth_id in reused:
                    existing = self.search([
                        ('authorization_id', '=', auth_id),
                        ('product_id', '=', vals.get('product_id')),
                    ], limit=1)
                    if existing:
                        result |= existing
                        continue
                fresh.append(vals)
            if fresh:
                result |= super().create(fresh)
            return result

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