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
    
    # ✅ Costo Mayor: Mantiene el máximo histórico en MXN
    x_costo_mayor = fields.Float(
        string='Costo Mayor (MXN)', 
        digits='Product Price', 
        default=0.0, 
        company_dependent=True,
        help="El monto más alto registrado de compra (incluye costos en destino)."
    )
    
    # ✅ Utilidad Real (Default 40% -> divisor 0.60)
    x_utilidad = fields.Float(string='% Utilidad', default=40.0, help="Ejemplo: 40 para margen del 40% (Costo / 0.60)")
    
    x_name_sps = fields.Char(string='Nombre SPS', help='Nombre del producto en el sistema SPS', default='')

    def _calculate_escalera_precios(self):
        """
        Calcula los 3 niveles de precios en MXN y USD basados en el Costo Mayor, 
        la utilidad y el tipo de cambio de Banorte.
        """
        # Obtenemos el tipo de cambio guardado por el cron
        rate_param = self.env['ir.config_parameter'].sudo().get_param('banorte.last_rate', '1.0')
        try:
            rate = float(rate_param)
        except:
            rate = 1.0
        
        for record in self:
            # Solo si hay un costo mayor registrado
            if record.x_costo_mayor > 0:
                # Utilidad Real: Costo / (1 - %)
                divisor = (1 - (record.x_utilidad / 100.0))
                if divisor <= 0:
                    divisor = 0.01
                
                # Cálculo Escalera MXN
                mxn_1 = record.x_costo_mayor / divisor
                mxn_2 = mxn_1 * 0.95  # Nivel 2: -5%
                mxn_3 = mxn_2 * 0.95  # Nivel 3: -5% adicional
                
                # Actualizar campos (Usamos sudo para evitar temas de permisos en procesos automáticos)
                record.sudo().write({
                    'x_price_mxn_1': mxn_1,
                    'x_price_mxn_2': mxn_2,
                    'x_price_mxn_3': mxn_3,
                    'x_price_usd_1': mxn_1 / rate if rate > 0 else 0,
                    'x_price_usd_2': mxn_2 / rate if rate > 0 else 0,
                    'x_price_usd_3': mxn_3 / rate if rate > 0 else 0,
                })

    def write(self, vals):
        """
        Captura cambios manuales y automáticos. 
        Odoo actualiza 'standard_price' incluso en procesos de Costo Promedio.
        """
        # Si viene una actualización de costo, verificamos si supera al mayor histórico
        if 'standard_price' in vals:
            new_cost = float(vals.get('standard_price', 0))
            for record in self:
                if new_cost > record.x_costo_mayor:
                    vals['x_costo_mayor'] = new_cost
        
        res = super(ProductTemplate, self).write(vals)

        # Disparar recálculo si cambió el costo mayor o la utilidad
        if 'x_costo_mayor' in vals or 'x_utilidad' in vals:
            self._calculate_escalera_precios()
            
        return res

    @api.model
    def cron_update_banorte_rates(self):
        """
        Actualiza tipo de cambio y recalcula todos los productos.
        """
        api_key = self.env['ir.config_parameter'].sudo().get_param('API_KEY')
        if not api_key:
            _logger.error("BANORTE SYNC: Falta API_KEY")
            return

        url = "https://api-banorte.recubrimientos.app/"
        headers = {"x-api-key": api_key}

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                rate_str = data.get("tipo-cambio-venta-banorte", "0").replace('$', '').strip()
                rate = float(rate_str)
                
                if rate > 0:
                    self.env['ir.config_parameter'].sudo().set_param('banorte.last_rate', rate)
                    # Recalcular todos los productos con costo
                    self.search([('x_costo_mayor', '>', 0)])._calculate_escalera_precios()
        except Exception as e:
            _logger.error(f"BANORTE SYNC Error: {e}")

    @api.model
    def get_custom_prices(self, product_id, currency_code):
        product = self.browse(product_id)
        prices = []
        is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        
        if currency_code == 'USD':
            prices.append({'label': 'Precio Alto (1)', 'value': product.x_price_usd_1, 'level': 'high'})
            prices.append({'label': 'Precio Medio (2)', 'value': product.x_price_usd_2, 'level': 'medium'})
            if is_authorizer:
                prices.append({'label': 'Precio Mínimo (3)', 'value': product.x_price_usd_3, 'level': 'minimum'})
        else:
            prices.append({'label': 'Precio Alto (1)', 'value': product.x_price_mxn_1, 'level': 'high'})
            prices.append({'label': 'Precio Medio (2)', 'value': product.x_price_mxn_2, 'level': 'medium'})
            if is_authorizer:
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
            medium = product.x_price_mxn_2 if currency_code == 'MXN' else product.x_price_usd_2
            if requested_price < (medium - 0.01):
                needs_auth.append({
                    'product_id': int(product_id_str),
                    'product_name': product.display_name,
                    'requested_price': requested_price,
                    'medium_price': medium,
                    'minimum_price': product.x_price_mxn_3 if currency_code == 'MXN' else product.x_price_usd_3
                })
        return {'needs_authorization': len(needs_auth) > 0, 'products': needs_auth}

class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        """
        EXTREMADAMENTE IMPORTANTE: 
        Odoo actualiza el costo promedio a nivel de 'product.product'.
        Si no interceptamos aquí, los cambios automáticos de inventario se pierden.
        """
        if 'standard_price' in vals:
            new_cost = float(vals.get('standard_price', 0))
            for product in self:
                # Verificamos contra el costo mayor del template
                if new_cost > product.product_tmpl_id.x_costo_mayor:
                    # Actualizamos el template, lo cual disparará su propio write y el recálculo
                    product.product_tmpl_id.sudo().write({'x_costo_mayor': new_cost})
        
        return super(ProductProduct, self).write(vals)