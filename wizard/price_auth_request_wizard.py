# -*- coding: utf-8 -*-
"""Solicitar autorización de precio desde la orden de venta (27 sep 2026).

Decisión del cliente: guardar una orden con precio bajo NO pide nada (solo
la marca como no autorizada). La solicitud nace aquí, al pulsar «Solicitar
Autorización de Precio»: el vendedor ve qué productos están por debajo y
contra qué precio, y la justificación es obligatoria.
"""
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SalePriceAuthRequestWizard(models.TransientModel):
    _name = 'sale.price.auth.request.wizard'
    _description = 'Solicitar autorización de precio'

    sale_order_id = fields.Many2one('sale.order', string='Orden', required=True, readonly=True)
    partner_id = fields.Many2one(related='sale_order_id.partner_id', string='Cliente')
    currency_id = fields.Many2one(related='sale_order_id.currency_id')
    line_ids = fields.One2many('sale.price.auth.request.wizard.line', 'wizard_id', string='Productos', readonly=True)
    is_reauth = fields.Boolean(compute='_compute_is_reauth')
    reason = fields.Text(
        'Justificación', required=True,
        help='Por qué se otorga este precio: cliente, volumen, competencia, proyecto… '
             'La lee el autorizador.')

    @api.depends('line_ids.kind')
    def _compute_is_reauth(self):
        for wiz in self:
            wiz.is_reauth = any(l.kind == 'reauth' for l in wiz.line_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env['sale.order'].browse(
            res.get('sale_order_id') or self.env.context.get('default_sale_order_id')).exists()
        if not order:
            return res
        commands = []
        for item in order._som_price_auth_lines():
            line = item['line']
            commands.append((0, 0, {
                'product_id': line.product_id.id,
                'quantity': line.product_uom_qty,
                'uom_name': (line.product_uom_id.name if 'product_uom_id' in line._fields
                             else line.product_uom.name) or '',
                'price_unit': line.price_unit,
                'reference_price': item['floor'] if item['reauth'] else item['threshold'],
                'kind': 'reauth' if item['reauth'] else 'below_level',
            }))
        res['line_ids'] = commands
        if order.x_price_auth_reason:
            res['reason'] = order.x_price_auth_reason
        return res

    def action_confirm(self):
        self.ensure_one()
        order = self.sale_order_id
        reason = (self.reason or '').strip()
        if len(reason) < 5:
            raise UserError(_('Escribe la justificación: es lo que lee el autorizador para decidir.'))
        if order.x_price_authorization_id and order.x_price_authorization_id.state == 'pending':
            raise UserError(_('La orden %s ya tiene la solicitud %s pendiente.') % (
                order.name, order.x_price_authorization_id.name))
        previous = order.x_price_authorization_id
        order.write({'x_price_auth_reason': reason})
        order.action_request_authorization()
        auth = order.x_price_authorization_id
        if not auth or auth == previous:
            raise UserError(_('No se pudo crear la solicitud de autorización de precios.'))
        order.message_post(body=Markup(
            '<p>📝 %s solicitó %s de precios: <b>%s</b>.</p><p>Justificación: %s</p>'
        ) % (self.env.user.name,
             _('RE-autorización') if self.is_reauth else _('autorización'),
             auth.name, reason), message_type='notification', subtype_xmlid='mail.mt_note')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Solicitud enviada'),
                'message': _('%s enviada a los autorizadores de precios.') % auth.name,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SalePriceAuthRequestWizardLine(models.TransientModel):
    _name = 'sale.price.auth.request.wizard.line'
    _description = 'Producto por autorizar'

    wizard_id = fields.Many2one('sale.price.auth.request.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', 'Producto', readonly=True)
    quantity = fields.Float('Cantidad', digits='Product Unit', readonly=True)
    uom_name = fields.Char('Unidad', readonly=True)
    price_unit = fields.Float('Precio capturado', digits='Product Price', readonly=True)
    reference_price = fields.Float('Precio de referencia', digits='Product Price', readonly=True,
                                   help='Precio mínimo sin autorización o, en re-autorización, el ya autorizado.')
    kind = fields.Selection([
        ('below_level', 'Por debajo del precio mínimo'),
        ('reauth', 'Por debajo de lo ya autorizado'),
    ], 'Motivo', readonly=True)
    difference_pct = fields.Float('Diferencia %', compute='_compute_difference_pct')

    @api.depends('price_unit', 'reference_price')
    def _compute_difference_pct(self):
        for line in self:
            ref = line.reference_price or 0.0
            line.difference_pct = ((line.price_unit - ref) / ref) if ref else 0.0
