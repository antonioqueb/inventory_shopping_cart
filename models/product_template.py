# ./models/product_template.py
# -*- coding: utf-8 -*-
import requests
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    # ✅ Campos de precios (Company Dependent)
    x_price_usd_1 = fields.Float(string='Precio USD 1 (Alto)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_2 = fields.Float(string='Precio USD 2 (Medio)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_3 = fields.Float(string='Precio USD 3 (Mínimo)', digits='Product Price', default=0.0, company_dependent=True)
    
    x_price_mxn_1 = fields.Float(string='Precio MXN 1 (Alto)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_2 = fields.Float(string='Precio MXN 2 (Medio)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_3 = fields.Float(string='Precio MXN 3 (Mínimo)', digits='Product Price', default=0.0, company_dependent=True)
    
    # ✅ Nuevo: Campo de Costo Mayor (Mantiene el histórico más alto en MXN)
    x_costo_mayor = fields.Float(
        string='Costo Mayor (MXN)', 
        digits='Product Price', 
        default=0.0, 
        company_dependent=True,
        help="El monto más alto registrado de compra (incluye costos en destino)."
    )
    
    # ✅ Nuevo: Porcentaje de Utilidad (Default 40%)
    x_utilidad = fields.Float(string='% Utilidad', default=40.0, help="Ejemplo: 40 para margen del 40% (Costo / 0.60)")
    
    x_name_sps = fields.Char(string='Nombre SPS', help='Nombre del producto en el sistema SPS', default='')

    def _calculate_escalera_precios(self):
        """
        Calcula los 3 niveles de precios en MXN y USD basados en el Costo Mayor, 
        la utilidad y el tipo de cambio de Banorte.
        """
        rate = float(self.env['ir.config_parameter'].sudo().get_param('banorte.last_rate', '1.0'))
        
        for record in self:
            if record.x_costo_mayor > 0:
                # 1. Calcular Utilidad Real (Fórmula: Costo / (1 - %Utilidad/100))
                # Si utilidad es 40, divisor es 0.60. Si es 30, divisor es 0.70.
                divisor = (1 - (record.x_utilidad / 100.0))
                if divisor <= 0:
                    divisor = 0.01 # Evitar división por cero
                
                # Nivel 1: Precio Alto (MXN)
                mxn_1 = record.x_costo_mayor / divisor
                # Nivel 2: -5% del Nivel 1
                mxn_2 = mxn_1 * 0.95
                # Nivel 3: -5% del Nivel 2
                mxn_3 = mxn_2 * 0.95
                
                # Actualizar campos MXN y convertir a USD usando el rate de Banorte
                record.write({
                    'x_price_mxn_1': mxn_1,
                    'x_price_mxn_2': mxn_2,
                    'x_price_mxn_3': mxn_3,
                    'x_price_usd_1': mxn_1 / rate if rate > 0 else 0,
                    'x_price_usd_2': mxn_2 / rate if rate > 0 else 0,
                    'x_price_usd_3': mxn_3 / rate if rate > 0 else 0,
                })

    def write(self, vals):
        """
        Sobrescribimos write para detectar si el costo nativo (standard_price) 
        es mayor al x_costo_mayor almacenado.
        """
        # Si se está actualizando el costo nativo (que incluye Landed Costs)
        if 'standard_price' in vals:
            for record in self:
                nuevo_costo = float(vals.get('standard_price', 0))
                if nuevo_costo > record.x_costo_mayor:
                    vals['x_costo_mayor'] = nuevo_costo

        res = super(ProductTemplate, self).write(vals)

        # Si cambió el costo mayor o la utilidad, recalcular la escalera
        if 'x_costo_mayor' in vals or 'x_utilidad' in vals:
            self._calculate_escalera_precios()
            
        return res

    @api.model
    def cron_update_banorte_rates(self):
        """
        Acción planificada para actualizar precios MXN basados en API Banorte.
        Actualiza el tipo de cambio y dispara el recálculo de la escalera.
        """
        api_key = self.env['ir.config_parameter'].sudo().get_param('API_KEY')
        if not api_key:
            _logger.error("BANORTE SYNC: No se encontró el parámetro 'API_KEY'.")
            return

        url = "https://api-banorte.recubrimientos.app/"
        headers = {"x-api-key": api_key}

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                rate_str = data.get("tipo-cambio-venta-banorte", "0")
                try:
                    rate = float(rate_str.replace('$', '').strip())
                except ValueError:
                    rate = 0.0
                
                if rate > 0:
                    _logger.info(f"BANORTE SYNC: Nuevo tipo de cambio: {rate}")
                    self.env['ir.config_parameter'].sudo().set_param('banorte.last_rate', rate)
                    
                    # Actualizar todos los productos que tengan un costo mayor
                    products = self.search([('x_costo_mayor', '>', 0)])
                    products._calculate_escalera_precios()
                else:
                    _logger.warning("BANORTE SYNC: Rate inválido.")
            else:
                _logger.error(f"BANORTE SYNC: Error API {response.status_code}")
        except Exception as e:
            _logger.error(f"BANORTE SYNC: Excepción {e}")

    @api.model
    def get_custom_prices(self, product_id, currency_code):
        product = self.browse(product_id)
        prices = []
        is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        is_seller = self.env.user.has_group('inventory_shopping_cart.group_seller')
        is_inventory_only = self.env.user.has_group('stock.group_stock_user') and not is_authorizer and not is_seller
        
        if is_inventory_only:
            return []
        
        # Lógica de visibilidad por grupos
        if currency_code == 'USD':
            if product.x_price_usd_1 > 0:
                prices.append({'label': 'Precio Alto (1)', 'value': product.x_price_usd_1, 'level': 'high'})
            if product.x_price_usd_2 > 0:
                prices.append({'label': 'Precio Medio (2)', 'value': product.x_price_usd_2, 'level': 'medium'})
            if is_authorizer and product.x_price_usd_3 > 0:
                prices.append({'label': 'Precio Mínimo (3)', 'value': product.x_price_usd_3, 'level': 'minimum'})
                    
        elif currency_code == 'MXN':
            if product.x_price_mxn_1 > 0:
                prices.append({'label': 'Precio Alto (1)', 'value': product.x_price_mxn_1, 'level': 'high'})
            if product.x_price_mxn_2 > 0:
                prices.append({'label': 'Precio Medio (2)', 'value': product.x_price_mxn_2, 'level': 'medium'})
            if is_authorizer and product.x_price_mxn_3 > 0:
                prices.append({'label': 'Precio Mínimo (3)', 'value': product.x_price_mxn_3, 'level': 'minimum'})
        
        return prices
    
    @api.model
    def check_price_authorization_needed(self, product_prices, currency_code):
        needs_auth = []
        is_seller = self.env.user.has_group('inventory_shopping_cart.group_seller')
        if not is_seller:
            return {'needs_authorization': False, 'products': []}
        
        for product_id_str, requested_price in product_prices.items():
            product = self.browse(int(product_id_str))
            medium_price = product.x_price_mxn_2 if currency_code == 'MXN' else product.x_price_usd_2
            minimum_price = product.x_price_mxn_3 if currency_code == 'MXN' else product.x_price_usd_3
            
            if requested_price < medium_price:
                needs_auth.append({
                    'product_id': int(product_id_str),
                    'product_name': product.display_name,
                    'requested_price': requested_price,
                    'medium_price': medium_price,
                    'minimum_price': minimum_price
                })
        return {'needs_authorization': len(needs_auth) > 0, 'products': needs_auth}