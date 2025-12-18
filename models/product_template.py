# ./models/product_template.py
# -*- coding: utf-8 -*-
import requests
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    # ✅ CORRECCIÓN: company_dependent=True para manejar precios por empresa
    x_price_usd_1 = fields.Float(string='Precio USD 1 (1)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_2 = fields.Float(string='Precio USD 2 (2)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_3 = fields.Float(string='Precio USD 3 (3)', digits='Product Price', default=0.0, company_dependent=True)
    
    x_price_mxn_1 = fields.Float(string='Precio MXN 1 (1)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_2 = fields.Float(string='Precio MXN 2 (2)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_3 = fields.Float(string='Precio MXN 3 (3)', digits='Product Price', default=0.0, company_dependent=True)
    
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
                
                try:
                    rate = float(rate_str.replace('$', '').strip())
                except ValueError:
                    rate = 0.0
                
                if rate > 0:
                    _logger.info(f"BANORTE SYNC: Tipo de cambio obtenido: {rate}. Iniciando actualización por empresa...")
                    self.env['ir.config_parameter'].sudo().set_param('banorte.last_rate', rate)
                    
                    # ✅ 3. ACTUALIZAR CADA EMPRESA INDIVIDUALMENTE
                    companies = self.env['res.company'].search([])
                    
                    for company in companies:
                        _logger.info(f"BANORTE SYNC: Procesando empresa {company.name}...")
                        
                        # Usamos with_company para que los campos company_dependent apunten a la empresa correcta
                        ProductCtx = self.with_company(company)
                        
                        products = ProductCtx.search([
                            '|', '|',
                            ('x_price_usd_1', '>', 0),
                            ('x_price_usd_2', '>', 0),
                            ('x_price_usd_3', '>', 0)
                        ])
                        
                        count = 0
                        for product in products:
                            updates = {}
                            # Al leer product.x_price_usd_1, Odoo trae el valor específico de la empresa actual
                            if product.x_price_usd_1:
                                updates['x_price_mxn_1'] = product.x_price_usd_1 * rate
                            if product.x_price_usd_2:
                                updates['x_price_mxn_2'] = product.x_price_usd_2 * rate
                            if product.x_price_usd_3:
                                updates['x_price_mxn_3'] = product.x_price_usd_3 * rate
                            
                            if updates:
                                product.write(updates)
                                count += 1
                                
                        _logger.info(f"BANORTE SYNC: Empresa {company.name} -> {count} productos actualizados.")
                else:
                    _logger.warning("BANORTE SYNC: El tipo de cambio obtenido es 0 o inválido.")
            else:
                _logger.error(f"BANORTE SYNC: Error {response.status_code} - {response.text}")
                
        except Exception as e:
            _logger.error(f"BANORTE SYNC: Excepción de conexión: {e}")

    @api.model
    def get_custom_prices(self, product_id, currency_code):
        # Odoo usa automáticamente la empresa del usuario actual
        product = self.browse(product_id)
        prices = []
        
        is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        is_seller = self.env.user.has_group('inventory_shopping_cart.group_seller')
        is_inventory_only = self.env.user.has_group('stock.group_stock_user') and not is_authorizer and not is_seller
        
        if is_inventory_only:
            return []
        
        if currency_code == 'USD':
            if is_authorizer:
                if product.x_price_usd_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_usd_1, 'level': 'high'})
                if product.x_price_usd_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_usd_2, 'level': 'medium'})
                if product.x_price_usd_3 > 0:
                    prices.append({'label': 'Precio Mínimo', 'value': product.x_price_usd_3, 'level': 'minimum'})
            elif is_seller:
                if product.x_price_usd_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_usd_1, 'level': 'high'})
                if product.x_price_usd_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_usd_2, 'level': 'medium'})
            else:
                if product.x_price_usd_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_usd_1, 'level': 'high'})
                if product.x_price_usd_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_usd_2, 'level': 'medium'})
                if product.x_price_usd_3 > 0:
                    prices.append({'label': 'Precio Mínimo', 'value': product.x_price_usd_3, 'level': 'minimum'})
                    
        elif currency_code == 'MXN':
            if is_authorizer:
                if product.x_price_mxn_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_mxn_1, 'level': 'high'})
                if product.x_price_mxn_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_mxn_2, 'level': 'medium'})
                if product.x_price_mxn_3 > 0:
                    prices.append({'label': 'Precio Mínimo', 'value': product.x_price_mxn_3, 'level': 'minimum'})
            elif is_seller:
                if product.x_price_mxn_1 > 0:
                    prices.append({'label': 'Precio Alto', 'value': product.x_price_mxn_1, 'level': 'high'})
                if product.x_price_mxn_2 > 0:
                    prices.append({'label': 'Precio Medio', 'value': product.x_price_mxn_2, 'level': 'medium'})
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
        needs_auth = []
        is_seller = self.env.user.has_group('inventory_shopping_cart.group_seller')
        
        if not is_seller:
            return {'needs_authorization': False, 'products': []}
        
        for product_id_str, requested_price in product_prices.items():
            product = self.browse(int(product_id_str))
            
            if currency_code == 'USD':
                medium_price = product.x_price_usd_2
                minimum_price = product.x_price_usd_3
            else:
                medium_price = product.x_price_mxn_2
                minimum_price = product.x_price_mxn_3
            
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