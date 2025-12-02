# ./models/product_template.py
# -*- coding: utf-8 -*-
import requests
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

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
    def cron_update_banorte_rates(self):
        """
        Acción planificada para actualizar precios MXN basados en API Banorte.
        Se ejecuta una vez al día.
        """
        # 1. Obtener API KEY del sistema
        api_key = self.env['ir.config_parameter'].sudo().get_param('API_KEY')
        if not api_key:
            _logger.error("BANORTE SYNC: No se encontró el parámetro 'API_KEY' en el sistema.")
            return

        url = "https://api-banorte.recubrimientos.app/"
        headers = {
            "x-api-key": api_key
        }

        try:
            # 2. Consultar API
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                rate_str = data.get("tipo-cambio-venta-banorte", "0")
                
                # Limpiar el string (ej: "$20.45" -> 20.45)
                rate = float(rate_str.replace('$', '').strip())
                
                if rate > 0:
                    _logger.info(f"BANORTE SYNC: Tipo de cambio obtenido: {rate}. Actualizando productos...")
                    
                    # 3. Guardar el tipo de cambio del día en parámetros (opcional, para referencia)
                    self.env['ir.config_parameter'].sudo().set_param('banorte.last_rate', rate)
                    
                    # 4. Actualizar masivamente los productos
                    # Buscamos productos que tengan algún precio en USD definido
                    products = self.search([
                        '|', '|',
                        ('x_price_usd_1', '>', 0),
                        ('x_price_usd_2', '>', 0),
                        ('x_price_usd_3', '>', 0)
                    ])
                    
                    count = 0
                    for product in products:
                        updates = {}
                        if product.x_price_usd_1:
                            updates['x_price_mxn_1'] = product.x_price_usd_1 * rate
                        if product.x_price_usd_2:
                            updates['x_price_mxn_2'] = product.x_price_usd_2 * rate
                        if product.x_price_usd_3:
                            updates['x_price_mxn_3'] = product.x_price_usd_3 * rate
                        
                        if updates:
                            product.write(updates)
                            count += 1
                            
                    _logger.info(f"BANORTE SYNC: Se actualizaron {count} productos con TC {rate}")
                else:
                    _logger.warning("BANORTE SYNC: El tipo de cambio obtenido es 0 o inválido.")
            else:
                _logger.error(f"BANORTE SYNC: Error {response.status_code} - {response.text}")
                
        except Exception as e:
            _logger.error(f"BANORTE SYNC: Excepción de conexión: {e}")

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