# ./models/product_template.py
# -*- coding: utf-8 -*-
import requests
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    # === CAMPOS LOGÍSTICOS Y DE COSTEO AVANZADO ===
    
    x_origin_country_id = fields.Many2one('res.country', string='País de Origen')
    
    x_pol_id = fields.Many2one(
        'res.partner', 
        string='Puerto de Carga (POL)',
        domain="[('category_id.name', '=', 'POL')]",
        help="Puerto donde se embarca la mercancía."
    )
    
    x_pod_id = fields.Many2one(
        'res.partner', 
        string='Puerto de Destino (POD)',
        domain="[('category_id.name', '=', 'POD')]",
        help="Puerto donde se descarga la mercancía."
    )
    
    x_container_capacity = fields.Float(
        string='Capacidad Contenedor (m²)',
        help="Cantidad de metros cuadrados de este material que caben en un contenedor estándar.",
        default=1.0
    )
    
    x_arancel_pct = fields.Float(
        string='Arancel (%)',
        help="Porcentaje de arancel aplicable sobre el costo bruto de compra.",
        default=0.0
    )

    # === CAMPOS DE RASTREO DE COSTOS ===

    x_has_purchases = fields.Boolean(string='Tiene Compras Confirmadas', compute='_compute_costo_all_in', store=True)
    
    x_max_avg_cost_mxn = fields.Float(
        string='Costo Bruto Histórico (MaxAvg)',
        digits='Product Price',
        readonly=True,
        help="El promedio ponderado histórico más alto registrado en compras (MXN)."
    )
    
    x_logistics_cost_mxn = fields.Float(
        string='Costo Logístico Unitario (MXN)',
        digits='Product Price',
        readonly=True,
        help="Costo del flete y gastos prorrateado por m² (Convertido de USD a MXN)."
    )
    
    x_duty_cost_mxn = fields.Float(
        string='Costo Arancel Unitario (MXN)',
        digits='Product Price',
        readonly=True,
        help="Costo de aranceles calculado sobre el Costo Bruto Base."
    )

    # === CAMPOS DE ESTRATEGIA DE PRECIOS (NUEVOS) ===
    
    x_utilidad = fields.Float(string='% Utilidad Base', default=40.0, help="Margen sobre el costo para el Precio Alto.")
    
    x_discount_medium = fields.Float(
        string='% Descuento Medio', 
        default=5.0, 
        help="Porcentaje que baja el precio Medio respecto al Alto."
    )
    
    x_discount_minimum = fields.Float(
        string='% Descuento Mínimo', 
        default=5.0, 
        help="Porcentaje que baja el precio Mínimo respecto al Medio."
    )

    # === CAMPOS DE PRECIOS CALCULADOS ===
    
    x_price_usd_1 = fields.Float(string='Precio USD 1 (Alto)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_2 = fields.Float(string='Precio USD 2 (Medio)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_3 = fields.Float(string='Precio USD 3 (Mínimo)', digits='Product Price', default=0.0, company_dependent=True)
    
    x_price_mxn_1 = fields.Float(string='Precio MXN 1 (Alto)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_2 = fields.Float(string='Precio MXN 2 (Medio)', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_3 = fields.Float(string='Precio MXN 3 (Mínimo)', digits='Product Price', default=0.0, company_dependent=True)
    
    # x_costo_mayor AHORA ES EL RESULTADO DE ALL-IN
    x_costo_mayor = fields.Float(
        string='Costo ALL-IN (MXN)', 
        digits='Product Price', 
        default=0.0, 
        company_dependent=True,
        readonly=True,
        help="Costo Total Calculado: Base + Logística + Aranceles (Solo si hay compras confirmadas)."
    )
    
    x_name_sps = fields.Char(string='Nombre SPS', help='Nombre del producto en el sistema SPS', default='')

    def action_update_costs(self):
        """Acción manual para recalcular costos"""
        _logger.info(f"COSTOS: Iniciando actualización manual para {self.name}")
        self._compute_costo_all_in()
        self._calculate_escalera_precios()

    def _compute_costo_all_in(self):
        """
        Calcula el costo 'All-In'.
        """
        usd_currency = self.env.ref('base.USD')
        company = self.env.company
        company_currency = company.currency_id
        
        for record in self:
            _logger.info(f"COSTOS: Calculando para producto {record.display_name} (ID: {record.id})")
            
            # 1. Búsqueda de compras (Detectar confirmadas sin recibir)
            purchase_lines = self.env['purchase.order.line'].search([
                ('product_id.product_tmpl_id', '=', record.id),
                ('state', 'in', ['purchase', 'done']) 
            ], order='date_order asc, id asc')

            has_purchases = bool(purchase_lines)
            record.x_has_purchases = has_purchases
            
            all_in_cost = 0.0
            
            # === ESCENARIO A: SIN COMPRAS CONFIRMADAS ===
            if not has_purchases:
                all_in_cost = record.standard_price
                _logger.info(f"COSTOS: Sin compras. Usando Costo Estándar: {all_in_cost}")
                
                record.x_max_avg_cost_mxn = 0.0
                record.x_logistics_cost_mxn = 0.0
                record.x_duty_cost_mxn = 0.0
            
            # === ESCENARIO B: CON COMPRAS CONFIRMADAS ===
            else:
                # 1. Calcular MaxAvg
                total_qty = 0.0
                total_val_mxn = 0.0
                max_avg = 0.0
                
                for line in purchase_lines:
                    if line.product_qty <= 0:
                        continue
                        
                    line_currency = line.currency_id
                    rate_date = line.order_id.date_approve or line.order_id.date_order or fields.Date.today()
                    
                    price_unit_mxn = line.price_unit
                    if line_currency != company_currency:
                        price_unit_mxn = line_currency._convert(
                            line.price_unit, 
                            company_currency, 
                            line.company_id, 
                            rate_date
                        )
                    
                    total_qty += line.product_qty
                    total_val_mxn += (line.product_qty * price_unit_mxn)
                    
                    current_avg = total_val_mxn / total_qty
                    
                    if current_avg > max_avg:
                        max_avg = current_avg
                
                base_gross_cost = max_avg
                record.x_max_avg_cost_mxn = max_avg

                # 2. Calcular Logística (Tarifario USD -> MXN)
                logistics_cost_mxn = 0.0
                
                if record.x_origin_country_id and record.x_pol_id and record.x_pod_id and record.x_container_capacity > 0:
                    tariff = self.env['freight.tariff'].search([
                        ('country_id', '=', record.x_origin_country_id.id),
                        ('pol_id', '=', record.x_pol_id.id),
                        ('pod_id', '=', record.x_pod_id.id),
                        ('state', '=', 'active')
                    ], order='create_date desc', limit=1)
                    
                    if tariff:
                        logistics_unit_usd = tariff.all_in / record.x_container_capacity
                        logistics_cost_mxn = usd_currency._convert(
                            logistics_unit_usd,
                            company_currency,
                            company,
                            fields.Date.today()
                        )
                
                record.x_logistics_cost_mxn = logistics_cost_mxn

                # 3. Calcular Arancel
                duty_cost_mxn = 0.0
                if record.x_arancel_pct > 0:
                    duty_cost_mxn = base_gross_cost * (record.x_arancel_pct / 100.0)
                
                record.x_duty_cost_mxn = duty_cost_mxn

                # 4. Suma Final
                all_in_cost = base_gross_cost + logistics_cost_mxn + duty_cost_mxn
            
            if all_in_cost != record.x_costo_mayor:
                record.sudo().write({'x_costo_mayor': all_in_cost})

    def _calculate_escalera_precios(self):
        """
        Calcula la escalera de precios usando los porcentajes configurables.
        """
        rate_param = self.env['ir.config_parameter'].sudo().get_param('banorte.last_rate', '0')
        try:
            banorte_rate = float(rate_param)
        except:
            banorte_rate = 0.0
            
        if banorte_rate <= 0:
            usd_currency = self.env.ref('base.USD')
            company_currency = self.env.company.currency_id
            banorte_rate = usd_currency._convert(1.0, company_currency, self.env.company, fields.Date.today())

        for record in self:
            if record.x_costo_mayor > 0:
                # 1. Calcular Precio Alto (Base + Utilidad)
                divisor = (1 - (record.x_utilidad / 100.0))
                if divisor <= 0: divisor = 0.01
                mxn_1 = record.x_costo_mayor / divisor
                
                # 2. Calcular factores de descuento (Default 5% si es 0, o lo que ponga el usuario)
                pct_medium = record.x_discount_medium if record.x_discount_medium >= 0 else 5.0
                pct_minimum = record.x_discount_minimum if record.x_discount_minimum >= 0 else 5.0
                
                factor_medium = 1 - (pct_medium / 100.0)
                factor_minimum = 1 - (pct_minimum / 100.0)
                
                # 3. Calcular cascada
                mxn_2 = mxn_1 * factor_medium
                mxn_3 = mxn_2 * factor_minimum
                
                # 4. Convertir a USD
                usd_1 = mxn_1 / banorte_rate if banorte_rate > 0 else 0
                usd_2 = mxn_2 / banorte_rate if banorte_rate > 0 else 0
                usd_3 = mxn_3 / banorte_rate if banorte_rate > 0 else 0
                
                record.sudo().write({
                    'x_price_mxn_1': mxn_1,
                    'x_price_mxn_2': mxn_2,
                    'x_price_mxn_3': mxn_3,
                    'x_price_usd_1': usd_1,
                    'x_price_usd_2': usd_2,
                    'x_price_usd_3': usd_3,
                })

    def write(self, vals):
        res = super(ProductTemplate, self).write(vals)
        triggers = [
            'standard_price', 
            'x_origin_country_id', 'x_pol_id', 'x_pod_id', 
            'x_container_capacity', 'x_arancel_pct'
        ]
        
        # Disparadores de recálculo de precios (incluyendo los nuevos campos)
        price_triggers = ['x_utilidad', 'x_discount_medium', 'x_discount_minimum']
        
        if any(f in vals for f in triggers):
            self._compute_costo_all_in()
            self._calculate_escalera_precios()
        elif any(f in vals for f in price_triggers):
            self._calculate_escalera_precios()
            
        return res

    @api.model
    def cron_update_banorte_rates(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param('API_KEY')
        if not api_key:
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
                    products = self.search([('active', '=', True)])
                    products._calculate_escalera_precios()
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
    def get_price_tooltip_data(self, product_id):
        """Retorna precios alto y medio en ambas monedas para el tooltip"""
        product = self.env['product.product'].browse(product_id)
        if not product.exists():
            return {}
        tmpl = product.product_tmpl_id
        return {
            'usd_high': tmpl.x_price_usd_1,
            'usd_medium': tmpl.x_price_usd_2,
            'mxn_high': tmpl.x_price_mxn_1,
            'mxn_medium': tmpl.x_price_mxn_2,
        }

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
        res = super(ProductProduct, self).write(vals)
        if 'standard_price' in vals:
            for product in self:
                product.product_tmpl_id._compute_costo_all_in()
                product.product_tmpl_id._calculate_escalera_precios()
        return res