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
        help="Costo del flete y gastos prorrateado por m²."
    )
    
    x_duty_cost_mxn = fields.Float(
        string='Costo Arancel Unitario (MXN)',
        digits='Product Price',
        readonly=True,
        help="Costo de aranceles calculado sobre el Costo Bruto Base."
    )

    # === CAMPOS EXISTENTES DE PRECIOS ===
    
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
        help="Costo Total Calculado: Base (Standard o MaxAvg) + Logística + Aranceles."
    )
    
    x_utilidad = fields.Float(string='% Utilidad', default=40.0, help="Ejemplo: 40 para margen del 40% (Costo / 0.60)")
    x_name_sps = fields.Char(string='Nombre SPS', help='Nombre del producto en el sistema SPS', default='')

    def action_update_costs(self):
        """Acción manual para recalcular costos"""
        self._compute_costo_all_in()
        self._calculate_escalera_precios()

    def _compute_costo_all_in(self):
        """
        Calcula el costo 'All-In' basado en la estrategia definida:
        1. Si NO hay compras: Costo Base = Standard Price.
        2. Si HAY compras: Costo Base = MaxAvg (Promedio Ponderado Histórico más alto).
        3. Suma Costos Logísticos (Tarifario / Capacidad).
        4. Suma Aranceles (% sobre Costo Base).
        """
        for record in self:
            # 1. Determinar Historial de Compras (MaxAvg)
            purchase_lines = self.env['purchase.order.line'].search([
                ('product_id.product_tmpl_id', '=', record.id),
                ('state', 'in', ['purchase', 'done']),
                ('qty_received', '>', 0) # Consideramos lo recibido o confirmado
            ], order='date_approve asc, id asc')

            has_purchases = bool(purchase_lines)
            record.x_has_purchases = has_purchases
            
            base_gross_cost = 0.0
            
            if not has_purchases:
                # CAMINO A: Sin compras confirmadas -> Usar costo estándar
                base_gross_cost = record.standard_price
                record.x_max_avg_cost_mxn = 0.0 # Informativo
            else:
                # CAMINO B: Con compras -> Calcular MaxAvg
                total_qty = 0.0
                total_val_mxn = 0.0
                max_avg = 0.0
                
                company_currency = self.env.company.currency_id

                for line in purchase_lines:
                    if line.product_qty <= 0:
                        continue
                        
                    # Conversión a MXN
                    line_currency = line.currency_id
                    # Usar fecha de aprobación o fecha de orden
                    rate_date = line.order_id.date_approve or line.order_id.date_order or fields.Date.today()
                    
                    price_unit_mxn = line.price_unit
                    if line_currency != company_currency:
                        price_unit_mxn = line_currency._convert(
                            line.price_unit, 
                            company_currency, 
                            line.company_id, 
                            rate_date
                        )
                    
                    # Acumular para promedio ponderado
                    total_qty += line.product_qty
                    total_val_mxn += (line.product_qty * price_unit_mxn)
                    
                    current_avg = total_val_mxn / total_qty
                    
                    # Regla: Respetar el promedio más alto histórico
                    if current_avg > max_avg:
                        max_avg = current_avg
                    # Si current_avg baja, max_avg se mantiene (no baja)

                base_gross_cost = max_avg
                record.x_max_avg_cost_mxn = max_avg

            # 2. Calcular Logística (Desde Tarifario)
            logistics_cost = 0.0
            if record.x_origin_country_id and record.x_pol_id and record.x_pod_id and record.x_container_capacity > 0:
                # Buscar tarifa vigente más reciente
                tariff = self.env['freight.tariff'].search([
                    ('country_id', '=', record.x_origin_country_id.id),
                    ('pol_id', '=', record.x_pol_id.id),
                    ('pod_id', '=', record.x_pod_id.id),
                    ('state', '=', 'active')
                ], order='create_date desc', limit=1)
                
                if tariff:
                    # Costo Total Contenedor (All In del tarifario) / Capacidad m2
                    logistics_cost = tariff.all_in / record.x_container_capacity
            
            record.x_logistics_cost_mxn = logistics_cost

            # 3. Calcular Arancel (% sobre el Costo Bruto Base)
            duty_cost = 0.0
            if record.x_arancel_pct > 0:
                duty_cost = base_gross_cost * (record.x_arancel_pct / 100.0)
            
            record.x_duty_cost_mxn = duty_cost

            # 4. Costo ALL IN Final
            all_in_cost = base_gross_cost + logistics_cost + duty_cost
            
            # Actualizamos x_costo_mayor (usando sudo para saltar reglas de permisos si es auto)
            if all_in_cost != record.x_costo_mayor:
                record.sudo().write({'x_costo_mayor': all_in_cost})

    def _calculate_escalera_precios(self):
        """
        Calcula los 3 niveles de precios en MXN y USD basados en el Costo Mayor (ALL-IN), 
        la utilidad y el tipo de cambio de Banorte.
        """
        rate_param = self.env['ir.config_parameter'].sudo().get_param('banorte.last_rate', '1.0')
        try:
            rate = float(rate_param)
        except:
            rate = 1.0
        
        for record in self:
            if record.x_costo_mayor > 0:
                # Utilidad Real: Costo / (1 - %)
                divisor = (1 - (record.x_utilidad / 100.0))
                if divisor <= 0:
                    divisor = 0.01
                
                # Cálculo Escalera MXN
                mxn_1 = record.x_costo_mayor / divisor
                mxn_2 = mxn_1 * 0.95  # Nivel 2: -5%
                mxn_3 = mxn_2 * 0.95  # Nivel 3: -5% adicional
                
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
        Intercepta cambios para recalcular costos si cambian variables críticas.
        """
        res = super(ProductTemplate, self).write(vals)

        # Campos que disparan recálculo de costos All-In
        triggers = [
            'standard_price', 
            'x_origin_country_id', 'x_pol_id', 'x_pod_id', 
            'x_container_capacity', 'x_arancel_pct'
        ]
        
        if any(f in vals for f in triggers):
            self._compute_costo_all_in()
            self._calculate_escalera_precios()

        # Si solo cambió la utilidad, recalcular solo precios
        elif 'x_utilidad' in vals:
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
                    # Recalcular escalera para todos los productos con costo calculado
                    products = self.search([('x_costo_mayor', '>', 0)])
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
        Al escribir en product.product (ej. cambios de costo std), 
        asegurar que el template se entere.
        """
        res = super(ProductProduct, self).write(vals)
        if 'standard_price' in vals:
            for product in self:
                # Disparar recálculo en el template
                product.product_tmpl_id._compute_costo_all_in()
                product.product_tmpl_id._calculate_escalera_precios()
        return res