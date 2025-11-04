# ./models/product_template.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    x_price_usd_1 = fields.Float(string='Precio USD 1 (Alto)', digits='Product Price', default=0.0)
    x_price_usd_2 = fields.Float(string='Precio USD 2 (Medio)', digits='Product Price', default=0.0)
    x_price_usd_3 = fields.Float(string='Precio USD 3 (Bajo)', digits='Product Price', default=0.0)
    
    x_price_mxn_1 = fields.Float(string='Precio MXN 1 (Alto)', digits='Product Price', default=0.0)
    x_price_mxn_2 = fields.Float(string='Precio MXN 2 (Medio)', digits='Product Price', default=0.0)
    x_price_mxn_3 = fields.Float(string='Precio MXN 3 (Bajo)', digits='Product Price', default=0.0)
    
    @api.model
    def get_custom_prices(self, product_id, currency_code):
        product = self.browse(product_id)
        prices = []
        
        if currency_code == 'USD':
            if product.x_price_usd_1 > 0:
                prices.append({'label': 'Precio Alto', 'value': product.x_price_usd_1})
            if product.x_price_usd_2 > 0:
                prices.append({'label': 'Precio Medio', 'value': product.x_price_usd_2})
            if product.x_price_usd_3 > 0:
                prices.append({'label': 'Precio Bajo', 'value': product.x_price_usd_3})
        elif currency_code == 'MXN':
            if product.x_price_mxn_1 > 0:
                prices.append({'label': 'Precio Alto', 'value': product.x_price_mxn_1})
            if product.x_price_mxn_2 > 0:
                prices.append({'label': 'Precio Medio', 'value': product.x_price_mxn_2})
            if product.x_price_mxn_3 > 0:
                prices.append({'label': 'Precio Bajo', 'value': product.x_price_mxn_3})
        
        return prices