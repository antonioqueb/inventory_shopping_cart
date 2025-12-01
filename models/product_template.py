# ./models/product_template.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    x_price_usd_1 = fields.Float(string='Precio USD 1 (Alto)', digits='Product Price', default=0.0)
    x_price_usd_2 = fields.Float(string='Precio USD 2 (Medio)', digits='Product Price', default=0.0)
    x_price_usd_3 = fields.Float(string='Precio USD 3 (Mínimo)', digits='Product Price', default=0.0)
    
    x_price_mxn_1 = fields.Float(string='Precio MXN 1 (Alto)', digits='Product Price', default=0.0)
    x_price_mxn_2 = fields.Float(string='Precio MXN 2 (Medio)', digits='Product Price', default=0.0)
    x_price_mxn_3 = fields.Float(string='Precio MXN 3 (Mínimo)', digits='Product Price', default=0.0)
    
    x_name_sps = fields.Char(string='Nombre SPS', help='Nombre del producto en el sistema SPS', default='')

    @api.model
    def get_custom_prices(self, product_id, currency_code):
        product = self.browse(product_id)
        prices = []
        
        # Verificar grupos del usuario
        is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        is_seller = self.env.user.has_group('inventory_shopping_cart.group_seller')
        is_inventory_only = self.env.user.has_group('stock.group_stock_user') and not is_authorizer and not is_seller
        
        # Perfil Inventario: NO ve ningún precio personalizado
        if is_inventory_only:
            return []
        
        if currency_code == 'USD':
            # Autorizadores ven TODO (Alto, Medio, Mínimo)
            if is_authorizer:
                if product.x_price_usd_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_usd_1, 'level': 'high'})
                if product.x_price_usd_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_usd_2, 'level': 'medium'})
                if product.x_price_usd_3 > 0:
                    prices.append({'label': 'Precio Mínimo', 'value': product.x_price_usd_3, 'level': 'minimum'})
            # Vendedores solo ven Alto y Medio
            elif is_seller:
                if product.x_price_usd_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_usd_1, 'level': 'high'})
                if product.x_price_usd_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_usd_2, 'level': 'medium'})
            # Otros usuarios (admin, etc.) ven todo
            else:
                if product.x_price_usd_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_usd_1, 'level': 'high'})
                if product.x_price_usd_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_usd_2, 'level': 'medium'})
                if product.x_price_usd_3 > 0:
                    prices.append({'label': 'Precio Mínimo', 'value': product.x_price_usd_3, 'level': 'minimum'})
                    
        elif currency_code == 'MXN':
            # Autorizadores ven TODO
            if is_authorizer:
                if product.x_price_mxn_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_mxn_1, 'level': 'high'})
                if product.x_price_mxn_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_mxn_2, 'level': 'medium'})
                if product.x_price_mxn_3 > 0:
                    prices.append({'label': 'Precio Mínimo', 'value': product.x_price_mxn_3, 'level': 'minimum'})
            # Vendedores solo Alto y Medio
            elif is_seller:
                if product.x_price_mxn_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_mxn_1, 'level': 'high'})
                if product.x_price_mxn_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_mxn_2, 'level': 'medium'})
            # Otros usuarios ven todo
            else:
                if product.x_price_mxn_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_mxn_1, 'level': 'high'})
                if product.x_price_mxn_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_mxn_2, 'level': 'medium'})
                if product.x_price_mxn_3 > 0:
                    prices.append({'label': 'Precio Mínimo', 'value': product.x_price_mxn_3, 'level': 'minimum'})
        
        return prices
    
    @api.model
    def check_price_authorization_needed(self, product_prices, currency_code):
        """
        Verifica si algún precio solicitado requiere autorización
        Solo aplica para vendedores que solicitan precio menor al medio
        """
        needs_auth = []
        is_seller = self.env.user.has_group('inventory_shopping_cart.group_seller')
        
        # Si no es vendedor, no necesita autorización
        if not is_seller:
            return {'needs_authorization': False, 'products': []}
        
        for product_id_str, requested_price in product_prices.items():
            product = self.browse(int(product_id_str))
            
            # Obtener precio medio y mínimo según la divisa
            if currency_code == 'USD':
                medium_price = product.x_price_usd_2
                minimum_price = product.x_price_usd_3
            else:  # MXN
                medium_price = product.x_price_mxn_2
                minimum_price = product.x_price_mxn_3
            
            # Si el precio solicitado es menor al medio, requiere autorización
            if requested_price < medium_price:
                needs_auth.append({
                    'product_id': int(product_id_str),
                    'product_name': product.display_name,
                    'requested_price': requested_price,
                    'medium_price': medium_price,
                    'minimum_price': minimum_price
                })
        
        return {
            'needs_authorization': len(needs_auth) > 0,
            'products': needs_auth
        }