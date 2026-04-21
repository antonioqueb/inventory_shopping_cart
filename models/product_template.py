# ./models/product_template.py
# -*- coding: utf-8 -*-
import math
import requests
import logging
import random
import re
from datetime import datetime, timedelta, time

from odoo import models, fields, api

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

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

    # === MODO DE PRECIO ===
    x_pricing_mode = fields.Selection([
        ('calculated', 'Calculado (Costo + Utilidad)'),
        ('fixed', 'Precio Fijo'),
    ], string='Modo de Precio', default='calculated',
       help="Calculado: Precio = Costo / (1 - %Utilidad). "
            "Fijo: Se parte de un precio fijo base y se aplican las utilidades como niveles de descuento.")

    x_fixed_price = fields.Float(
        string='Precio Fijo Base (MXN)',
        digits='Product Price',
        default=0.0,
        help="Precio base fijo en MXN. "
             "Nivel 1 = este precio. "
             "Nivel 2 = Precio Fijo * (1 - %Utilidad Media / 100). "
             "Nivel 3 = Precio Fijo * (1 - %Utilidad Mínima / 100)."
    )

    # === ESTRATEGIA DE PRECIOS: UTILIDADES DIRECTAS ===
    
    x_utilidad = fields.Float(string='% Utilidad Alta', default=40.0,
                              help="Margen de utilidad para el Precio Alto (Nivel 1). Precio = Costo / (1 - %).")
    
    x_utilidad_media = fields.Float(
        string='% Utilidad Media', 
        default=35.0, 
        help="Margen de utilidad para el Precio Medio (Nivel 2). Precio = Costo / (1 - %)."
    )
    
    x_utilidad_minima = fields.Float(
        string='% Utilidad Mínima', 
        default=30.0, 
        help="Margen de utilidad para el Precio Mínimo (Nivel 3). Precio = Costo / (1 - %)."
    )

    # === CAMPOS DE PRECIOS CALCULADOS ===
    
    x_price_usd_1 = fields.Float(string='Precio USD 1', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_2 = fields.Float(string='Precio USD 2', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_3 = fields.Float(string='Precio USD 3', digits='Product Price', default=0.0, company_dependent=True)
    
    x_price_mxn_1 = fields.Float(string='Precio MXN 1', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_2 = fields.Float(string='Precio MXN 2', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_3 = fields.Float(string='Precio MXN 3', digits='Product Price', default=0.0, company_dependent=True)
    
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
            
            purchase_lines = self.env['purchase.order.line'].search([
                ('product_id.product_tmpl_id', '=', record.id),
                ('state', 'in', ['purchase', 'done']) 
            ], order='date_order asc, id asc')

            has_purchases = bool(purchase_lines)
            record.x_has_purchases = has_purchases
            
            all_in_cost = 0.0
            
            if not has_purchases:
                all_in_cost = record.standard_price
                _logger.info(f"COSTOS: Sin compras. Usando Costo Estándar: {all_in_cost}")
                
                record.x_max_avg_cost_mxn = 0.0
                record.x_logistics_cost_mxn = 0.0
                record.x_duty_cost_mxn = 0.0
            
            else:
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

                duty_cost_mxn = 0.0
                if record.x_arancel_pct > 0:
                    duty_cost_mxn = base_gross_cost * (record.x_arancel_pct / 100.0)
                
                record.x_duty_cost_mxn = duty_cost_mxn

                all_in_cost = base_gross_cost + logistics_cost_mxn + duty_cost_mxn
            
            if all_in_cost != record.x_costo_mayor:
                record.sudo().write({'x_costo_mayor': all_in_cost})

    def _calculate_escalera_precios(self):
        """
        Calcula la escalera de precios.
        """
        rate_param = self.env['ir.config_parameter'].sudo().get_param('banorte.last_rate', '0')
        try:
            banorte_rate = float(rate_param)
        except Exception:
            banorte_rate = 0.0
            
        if banorte_rate <= 0:
            usd_currency = self.env.ref('base.USD')
            company_currency = self.env.company.currency_id
            banorte_rate = usd_currency._convert(1.0, company_currency, self.env.company, fields.Date.today())

        def _price_from_utility(base, utility_pct):
            divisor = (1 - (utility_pct / 100.0))
            if divisor <= 0:
                divisor = 0.01
            return math.ceil(base / divisor)

        for record in self:
            mxn_1 = 0
            mxn_2 = 0
            mxn_3 = 0

            if record.x_pricing_mode == 'fixed' and record.x_fixed_price > 0:
                base = record.x_fixed_price
            else:
                base = record.x_costo_mayor

            if base > 0:
                mxn_1 = _price_from_utility(base, record.x_utilidad)
                mxn_2 = _price_from_utility(base, record.x_utilidad_media)
                mxn_3 = _price_from_utility(base, record.x_utilidad_minima)

            usd_1 = math.ceil(mxn_1 / banorte_rate) if banorte_rate > 0 else 0
            usd_2 = math.ceil(mxn_2 / banorte_rate) if banorte_rate > 0 else 0
            usd_3 = math.ceil(mxn_3 / banorte_rate) if banorte_rate > 0 else 0
            
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
        
        price_triggers = [
            'x_utilidad', 'x_utilidad_media', 'x_utilidad_minima',
            'x_pricing_mode', 'x_fixed_price',
        ]
        
        if any(f in vals for f in triggers):
            self._compute_costo_all_in()
            self._calculate_escalera_precios()
        elif any(f in vals for f in price_triggers):
            self._calculate_escalera_precios()
            
        return res

    # ============================================================
    # BANORTE SYNC
    # ============================================================

    @api.model
    def _banorte_local_tz(self):
        return ZoneInfo("America/Monterrey") if ZoneInfo else None

    @api.model
    def _parse_money_to_float(self, value):
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)

        cleaned = str(value).strip()
        cleaned = cleaned.replace('$', '').replace(',', '').strip()
        cleaned = re.sub(r'[^0-9.\-]', '', cleaned)

        return float(cleaned or 0.0)

    @api.model
    def _get_next_banorte_run_utc(self, now_utc=None):
        """
        Ventana local: 08:00 a 20:00 (Monterrey)
        Saltos variables: 45, 60, 75, 90 min
        Devuelve datetime UTC naive para guardar en ir_cron.nextcall
        """
        tz = self._banorte_local_tz()
        now_utc = now_utc or datetime.utcnow()

        if tz:
            now_local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
        else:
            now_local = now_utc

        intervals = [45, 60, 75, 90]
        start_day = time(8, 0)
        end_day = time(20, 0)

        if now_local.time() < start_day:
            candidate_local = now_local.replace(hour=8, minute=0, second=0, microsecond=0)
            candidate_local += timedelta(minutes=random.choice(intervals))
        elif now_local.time() >= end_day:
            next_day = now_local.date() + timedelta(days=1)
            candidate_local = datetime.combine(next_day, time(8, 0))
            if tz:
                candidate_local = candidate_local.replace(tzinfo=tz)
            candidate_local += timedelta(minutes=random.choice(intervals))
        else:
            candidate_local = now_local + timedelta(minutes=random.choice(intervals))
            if candidate_local.time() >= end_day:
                next_day = candidate_local.date() + timedelta(days=1)
                candidate_local = datetime.combine(next_day, time(8, 0))
                if tz:
                    candidate_local = candidate_local.replace(tzinfo=tz)
                candidate_local += timedelta(minutes=random.choice(intervals))

        if tz:
            candidate_utc = candidate_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        else:
            candidate_utc = candidate_local

        return candidate_utc

    @api.model
    def _reschedule_banorte_cron_sql(self):
        """
        Odoo 19 no permite write() al mismo cron mientras está ejecutándose.
        Por eso aquí se actualiza nextcall vía SQL.
        """
        cron = self.env.ref('inventory_shopping_cart.ir_cron_update_banorte_prices', raise_if_not_found=False)
        if not cron:
            _logger.warning("BANORTE SYNC: No se encontró el cron inventory_shopping_cart.ir_cron_update_banorte_prices")
            return

        next_run_utc = self._get_next_banorte_run_utc()
        nextcall_str = fields.Datetime.to_string(next_run_utc)

        self.env.cr.execute("""
            UPDATE ir_cron
               SET nextcall = %s,
                   write_date = NOW(),
                   write_uid = %s
             WHERE id = %s
        """, (nextcall_str, self.env.user.id or 1, cron.id))

        _logger.info("BANORTE SYNC: siguiente ejecución programada en %s UTC", nextcall_str)

    @api.model
    def cron_update_banorte_rates(self):
        """
        Consulta API Banorte, actualiza tipos de cambio y reprograma el cron.
        """
        icp = self.env['ir.config_parameter'].sudo()
        api_key = icp.get_param('API_KEY')

        # NO uses 127.0.0.1 si Odoo está en contenedor distinto al scraper.
        # Usa el nombre del servicio docker, por ejemplo:
        # http://banorte_scraper:8000/
        url = icp.get_param('BANORTE_API_URL', 'http://banorte_scraper:8000/')

        if not api_key:
            _logger.warning("BANORTE SYNC: API_KEY no configurada")
            self._reschedule_banorte_cron_sql()
            return False

        headers = {"x-api-key": api_key}

        try:
            response = requests.get(url, headers=headers, timeout=90)
            response.raise_for_status()

            data = response.json()

            buy_raw = data.get("tipo-cambio-compra-banorte")
            sell_raw = data.get("tipo-cambio-venta-banorte")

            rate_buy = self._parse_money_to_float(buy_raw)
            rate_sell = self._parse_money_to_float(sell_raw)

            if rate_sell <= 0:
                raise ValueError(f"Tipo de cambio venta inválido: {sell_raw}")

            icp.set_param('banorte.last_rate', rate_sell)
            icp.set_param('banorte.last_rate_buy', rate_buy)
            icp.set_param('banorte.last_rate_sell', rate_sell)
            icp.set_param('banorte.last_payload', str(data))
            icp.set_param('banorte.last_sync_at', fields.Datetime.now())

            products = self.search([('active', '=', True)])
            products._calculate_escalera_precios()

            _logger.info(
                "BANORTE SYNC OK | compra=%s venta=%s | productos recalculados=%s",
                rate_buy, rate_sell, len(products)
            )

            return True

        except Exception as e:
            _logger.exception("BANORTE SYNC Error: %s", e)
            return False

        finally:
            self._reschedule_banorte_cron_sql()

    @api.model
    def get_custom_prices(self, product_id, currency_code):
        product = self.browse(product_id)
        prices = []
        is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        
        if currency_code == 'USD':
            prices.append({'label': 'Precio  (1)', 'value': product.x_price_usd_1, 'level': 'high'})
            prices.append({'label': 'Precio  (2)', 'value': product.x_price_usd_2, 'level': 'medium'})
            if is_authorizer:
                prices.append({'label': 'Precio  (3)', 'value': product.x_price_usd_3, 'level': 'minimum'})
        else:
            prices.append({'label': 'Precio  (1)', 'value': product.x_price_mxn_1, 'level': 'high'})
            prices.append({'label': 'Precio  (2)', 'value': product.x_price_mxn_2, 'level': 'medium'})
            if is_authorizer:
                prices.append({'label': 'Precio  (3)', 'value': product.x_price_mxn_3, 'level': 'minimum'})
        return prices

    @api.model
    def get_price_tooltip_data(self, product_id):
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
        is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')
        if is_authorizer:
            return {'needs_authorization': False, 'products': [], 'is_authorizer': True}

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