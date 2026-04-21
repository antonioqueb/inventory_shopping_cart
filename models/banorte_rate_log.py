# -*- coding: utf-8 -*-
from odoo import models, fields


class BanorteRateLog(models.Model):
    _name = 'banorte.rate.log'
    _description = 'Histórico de tipo de cambio Banorte'
    _order = 'requested_at desc'

    requested_at = fields.Datetime(string='Fecha consulta', required=True, default=fields.Datetime.now, index=True)
    rate_buy = fields.Float(string='Compra', digits=(12, 4), required=True)
    rate_sell = fields.Float(string='Venta', digits=(12, 4), required=True)
    raw_response = fields.Text(string='Respuesta cruda')
    source_url = fields.Char(string='URL origen')
    success = fields.Boolean(string='Éxito', default=True)
    error_message = fields.Text(string='Error')