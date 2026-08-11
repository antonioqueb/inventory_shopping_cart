# -*- coding: utf-8 -*-
import base64
from urllib.parse import quote

from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Reporte por modelo y variante. El PDF se comparte por la hoja NATIVA del
# sistema (Web Share API) DENTRO del gesto del usuario — el contacto se
# elige ahí mismo, sin capturar teléfono. Fallback (equipos sin Web
# Share): wa.me/?text= con liga de descarga — WhatsApp pide elegir el
# contacto.
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
    report_choice = fields.Selection([
        ('detail', 'Reporte detallado'),
        ('summary', 'Resumen'),
    ], string='Documento a enviar', default='detail', required=True)

    # Payload PRE-CALCULADO (compute → viaja al cliente con cada cambio del
    # radio): al tocar Compartir, el JS solo descarga el PDF y abre la hoja
    # nativa — sin viajes extra que maten el gesto del usuario.
    x_report_name = fields.Char(compute='_compute_share_payload')
    x_filename = fields.Char(compute='_compute_share_payload')
    x_message = fields.Text(compute='_compute_share_payload')

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
            },
        }

    def _som_record(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_('El documento ya no existe.'))
        return record

    def _som_build_message(self, record):
        self.ensure_one()
        if self.res_model == 'sale.order':
            label = ('su orden de venta'
                     if getattr(record, 'state', '') in ('sale', 'done')
                     else 'su cotización')
        else:
            label = 'su reserva de material'
        partner_name = (self.partner_id.name or '').strip()
        saludo = 'Buen día%s:' % (' ' + partner_name if partner_name else '')
        # Sin remitente a propósito: quien envía queda claro por el número.
        return (
            '%s\n\n'
            'Le compartimos el %s de %s *%s*.\n\n'
            'Quedamos atentos a cualquier duda. Saludos cordiales.'
        ) % (
            saludo,
            'reporte detallado' if self.report_choice == 'detail' else 'resumen',
            label, record.display_name,
        )

    @api.depends('res_model', 'res_id', 'report_choice', 'partner_id')
    def _compute_share_payload(self):
        for wiz in self:
            wiz.x_report_name = ''
            wiz.x_filename = ''
            wiz.x_message = ''
            if not wiz.res_model or not wiz.res_id:
                continue
            record = wiz.env.get(wiz.res_model)
            record = record.browse(wiz.res_id).exists() if record is not None else None
            if not record:
                continue
            ref = (REPORTS.get(wiz.res_model) or {}).get(wiz.report_choice)
            if not ref:
                continue
            report = wiz.env.ref(ref, raise_if_not_found=False)
            if not report:
                continue
            variant = 'Detalle' if wiz.report_choice == 'detail' else 'Resumen'
            wiz.x_report_name = report.report_name
            wiz.x_filename = '%s - %s.pdf' % (
                (record.display_name or 'Documento').replace('/', '-'), variant)
            wiz.x_message = wiz._som_build_message(record)

    @api.model
    def get_fallback_wa_url(self, res_model, res_id, report_choice):
        """Plan B (sin Web Share): genera el PDF como adjunto con token y
        regresa wa.me/?text= — WhatsApp abre con selector de contacto y el
        mensaje trae la liga de descarga."""
        record = self.env[res_model].browse(int(res_id)).exists()
        if not record:
            raise UserError(_('El documento ya no existe.'))
        ref = (REPORTS.get(res_model) or {}).get(report_choice)
        if not ref:
            raise UserError(_('No hay reporte configurado.'))
        pdf, _ptype = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
            ref, [record.id])
        variant = 'Detalle' if report_choice == 'detail' else 'Resumen'
        fname = '%s - %s.pdf' % (
            (record.display_name or 'Documento').replace('/', '-'), variant)
        att = self.env['ir.attachment'].sudo().create({
            'name': fname,
            'type': 'binary',
            'datas': base64.b64encode(pdf),
            'res_model': res_model,
            'res_id': record.id,
            'mimetype': 'application/pdf',
        })
        att.generate_access_token()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        link = '%s/web/content/%s?download=true&access_token=%s' % (
            base_url, att.id, att.access_token)
        wiz = self.new({'res_model': res_model, 'res_id': int(res_id),
                        'report_choice': report_choice,
                        'partner_id': getattr(record, 'partner_id',
                                              self.env['res.partner']).id})
        message = wiz._som_build_message(record) + (
            '\n\nPuede descargar el documento aquí:\n%s' % link)
        return 'https://wa.me/?text=%s' % quote(message)

    @api.model
    def log_shared(self, res_model, res_id, report_choice):
        record = self.env[res_model].browse(int(res_id)).exists()
        if record and hasattr(record, 'message_post'):
            record.message_post(body=_(
                'Documento compartido por WhatsApp (%s).'
            ) % ('Detalle' if report_choice == 'detail' else 'Resumen'))
        return True


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
