# -*- coding: utf-8 -*-
import base64
import re
from urllib.parse import quote

from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Reporte por modelo y variante. El envío es por ENLACE wa.me (sin API de
# WhatsApp): abre la app del usuario con el mensaje listo — el archivo viaja
# como liga de descarga con token (WhatsApp no permite adjuntar por URL).
REPORTS = {
    'sale.order': {
        'detail': 'stock_lot_dimensions.action_report_sale_order_custom_detail',
        'summary': 'sale.action_report_saleorder',
    },
    'stock.lot.hold.order': {
        'detail': 'stock_lot_dimensions.action_report_stock_lot_hold_order_detail',
        'summary': 'stock_lot_dimensions.action_report_stock_lot_hold_order_summary',
    },
}


class SomWhatsappSend(models.TransientModel):
    _name = 'som.whatsapp.send'
    _description = 'Enviar documento por WhatsApp'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', readonly=True)
    phone = fields.Char(
        string='WhatsApp del cliente', required=True,
        help='Con lada internacional; a 10 dígitos se antepone 52 (México).')
    report_choice = fields.Selection([
        ('detail', 'Reporte detallado'),
        ('summary', 'Resumen'),
    ], string='Documento a enviar', default='detail', required=True)

    @api.model
    def _som_open_for(self, record, partner):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Enviar por WhatsApp'),
            'res_model': 'som.whatsapp.send',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': record._name,
                'default_res_id': record.id,
                'default_partner_id': partner.id if partner else False,
                'default_phone': (partner.phone or '') if partner else '',
            },
        }

    def _som_record(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_('El documento ya no existe.'))
        return record

    @staticmethod
    def _som_normalize_phone(phone):
        digits = re.sub(r'\D', '', phone or '')
        if len(digits) == 10:
            digits = '52' + digits
        if len(digits) < 11:
            raise UserError(_(
                'El número "%s" no parece un WhatsApp válido: captúralo '
                'con lada (10 dígitos nacionales o formato internacional).'
            ) % (phone or ''))
        return digits

    def action_send(self):
        self.ensure_one()
        record = self._som_record()
        report_ref = (REPORTS.get(self.res_model) or {}).get(self.report_choice)
        if not report_ref:
            raise UserError(_('No hay reporte configurado para este documento.'))

        pdf, _ptype = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
            report_ref, [record.id])

        variant = ('Detalle' if self.report_choice == 'detail' else 'Resumen')
        fname = '%s - %s.pdf' % (
            (record.display_name or 'Documento').replace('/', '-'), variant)
        att = self.env['ir.attachment'].sudo().create({
            'name': fname,
            'type': 'binary',
            'datas': base64.b64encode(pdf),
            'res_model': self.res_model,
            'res_id': record.id,
            'mimetype': 'application/pdf',
        })
        att.generate_access_token()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        link = '%s/web/content/%s?download=true&access_token=%s' % (
            base_url, att.id, att.access_token)

        if self.res_model == 'sale.order':
            label = ('su orden de venta'
                     if getattr(record, 'state', '') in ('sale', 'done')
                     else 'su cotización')
        else:
            label = 'su reserva de material'

        partner_name = (self.partner_id.name or '').strip()
        saludo = 'Buen día%s:' % (' ' + partner_name if partner_name else '')
        # Sin remitente a propósito: quien envía queda claro por el número.
        message = (
            '%s\n\n'
            'Le compartimos el %s de %s *%s*.\n\n'
            'Puede consultarlo y descargarlo aquí:\n%s\n\n'
            'Quedamos atentos a cualquier duda. Saludos cordiales.'
        ) % (
            saludo,
            'reporte detallado' if self.report_choice == 'detail' else 'resumen',
            label, record.display_name, link,
        )

        record.message_post(body=_(
            'Documento enviado por WhatsApp (%s) al %s: %s'
        ) % (variant, self.phone, fname))

        # Hoja NATIVA de compartir (Web Share API): en móvil el PDF viaja
        # ADJUNTO de verdad (el usuario elige WhatsApp y sale el archivo
        # con el mensaje). En escritorio sin Web Share cae a wa.me con la
        # liga de descarga dentro del mensaje.
        wa_url = 'https://wa.me/%s?text=%s' % (
            self._som_normalize_phone(self.phone), quote(message))
        return {
            'type': 'ir.actions.client',
            'tag': 'som_share_pdf',
            'params': {
                'url': link,
                'filename': fname,
                'message': message,
                'wa_url': wa_url,
            },
        }


class SaleOrderWhatsapp(models.Model):
    _inherit = 'sale.order'

    def action_open_whatsapp_send(self):
        self.ensure_one()
        return self.env['som.whatsapp.send']._som_open_for(
            self, self.partner_id)


class StockLotHoldOrderWhatsapp(models.Model):
    _inherit = 'stock.lot.hold.order'

    def action_open_whatsapp_send(self):
        self.ensure_one()
        return self.env['som.whatsapp.send']._som_open_for(
            self, self.partner_id)
