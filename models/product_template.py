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

# ÚNICA URL usada por el módulo para Banorte
BANORTE_API_URL = "http://banorte_scraper:8000/"


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # === CAMPOS LOGÍSTICOS Y DE COSTEO AVANZADO ===

    x_origin_country_id = fields.Many2one(
        'res.country',
        string='País de Origen'
    )

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

    # === TIPO DE CAMBIO USADO PARA COSTEO ===

    x_cost_exchange_rate = fields.Float(
        string='TC Costeo USD → MXN',
        digits=(12, 4),
        readonly=True,
        help="Tipo de cambio usado para convertir costos logísticos USD a MXN."
    )

    x_cost_exchange_rate_source = fields.Char(
        string='Fuente TC Costeo',
        readonly=True,
        help="Fuente del tipo de cambio usado para el costeo logístico."
    )

    x_cost_exchange_rate_last_sync = fields.Datetime(
        string='Última Sync Banorte',
        readonly=True,
        help="Última fecha/hora registrada de sincronización del TC Banorte."
    )

    # === CAMPOS DE RASTREO DE COSTOS ===

    x_has_purchases = fields.Boolean(
        string='Tiene Compras Confirmadas',
        compute='_compute_costo_all_in',
        store=True
    )

    x_max_avg_cost_mxn = fields.Float(
        string='Costo Bruto Histórico (MaxAvg)',
        digits='Product Price',
        readonly=True,
        help="El promedio ponderado histórico más alto registrado en compras (MXN)."
    )

    x_cost_base_mxn = fields.Float(
        string='Costo Base Usado (MXN)',
        digits='Product Price',
        readonly=True,
        help="Costo base realmente usado para el cálculo ALL-IN. Si hay compras, usa MaxAvg. Si no hay compras, usa costo estándar."
    )

    x_cost_base_usd = fields.Float(
        string='Costo Base Usado (USD)',
        digits='Product Price',
        readonly=True,
        help="Costo base usado convertido a USD con el TC de costeo."
    )

    x_freight_tariff_all_in_usd = fields.Float(
        string='Tarifa All-In Contenedor (USD)',
        digits='Product Price',
        readonly=True,
        help="Tarifa logística All-In del contenedor en USD tomada del tarifario."
    )

    x_logistics_cost_usd = fields.Float(
        string='Costo Logístico Unitario (USD)',
        digits='Product Price',
        readonly=True,
        help="Costo logístico unitario por m² en USD."
    )

    x_logistics_cost_mxn = fields.Float(
        string='Costo Logístico Unitario (MXN)',
        digits='Product Price',
        readonly=True,
        help="Costo del flete y gastos prorrateado por m² convertido con TC Banorte venta."
    )

    x_duty_cost_usd = fields.Float(
        string='Costo Arancel Unitario (USD)',
        digits='Product Price',
        readonly=True,
        help="Costo de aranceles convertido a USD con el TC de costeo."
    )

    x_duty_cost_mxn = fields.Float(
        string='Costo Arancel Unitario (MXN)',
        digits='Product Price',
        readonly=True,
        help="Costo de aranceles calculado sobre el Costo Bruto Base."
    )

    x_costo_mayor_usd = fields.Float(
        string='Costo ALL-IN (USD)',
        digits='Product Price',
        readonly=True,
        help="Costo ALL-IN convertido a USD con el TC de costeo."
    )

    x_costo_mayor = fields.Float(
        string='Costo ALL-IN (MXN)',
        digits='Product Price',
        default=0.0,
        company_dependent=True,
        readonly=True,
        help="Costo Total Calculado: Base + Logística + Aranceles."
    )

    x_logistics_calc_summary = fields.Char(
        string='Cálculo Logístico',
        readonly=True,
        help="Resumen de cálculo de logística: tarifa / capacidad × TC."
    )

    x_cost_calc_summary = fields.Text(
        string='Resumen del Cálculo ALL-IN',
        readonly=True,
        help="Resumen completo del cálculo en MXN y USD."
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

    x_utilidad = fields.Float(
        string='% Utilidad Alta',
        default=40.0,
        help="Margen de utilidad para el Precio Alto (Nivel 1). Precio = Costo / (1 - %)."
    )

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

    x_name_sps = fields.Char(
        string='Nombre SPS',
        help='Nombre del producto en el sistema SPS',
        default=''
    )

    # ============================================================
    # HELPERS TIPO DE CAMBIO
    # ============================================================

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
    def _get_banorte_usd_to_mxn_rate(self):
        """
        Devuelve el TC Banorte venta para convertir USD -> MXN.

        Prioridad:
        1. banorte.last_rate_sell
        2. banorte.last_rate
        """
        icp = self.env['ir.config_parameter'].sudo()

        for key in ('banorte.last_rate_sell', 'banorte.last_rate'):
            raw_rate = icp.get_param(key, '0')

            try:
                rate = self._parse_money_to_float(raw_rate)
            except Exception:
                rate = 0.0

            if rate > 0:
                return rate

        return 0.0

    @api.model
    def _get_costing_rate_info(self, company=None):
        """
        Devuelve información completa del TC usado para costeo.
        """
        company = company or self.env.company
        company_currency = company.currency_id
        usd_currency = self.env.ref('base.USD', raise_if_not_found=False)
        icp = self.env['ir.config_parameter'].sudo()

        last_sync = icp.get_param('banorte.last_sync_at') or False

        if not company_currency or not usd_currency:
            return {
                'rate': 0.0,
                'source': 'No se encontró moneda USD o moneda de compañía',
                'last_sync': last_sync,
            }

        if company_currency == usd_currency:
            return {
                'rate': 1.0,
                'source': 'Moneda de compañía USD',
                'last_sync': last_sync,
            }

        if company_currency.name == 'MXN':
            rate_sell = self._parse_money_to_float(icp.get_param('banorte.last_rate_sell', '0'))
            if rate_sell > 0:
                return {
                    'rate': rate_sell,
                    'source': 'Banorte venta (banorte.last_rate_sell)',
                    'last_sync': last_sync,
                }

            rate_last = self._parse_money_to_float(icp.get_param('banorte.last_rate', '0'))
            if rate_last > 0:
                return {
                    'rate': rate_last,
                    'source': 'Banorte last_rate',
                    'last_sync': last_sync,
                }

            _logger.warning(
                "COSTOS: No hay TC Banorte válido en banorte.last_rate_sell/banorte.last_rate. "
                "Se usará TC estándar de Odoo como fallback."
            )

        try:
            fallback_rate = usd_currency._convert(
                1.0,
                company_currency,
                company,
                fields.Date.today()
            )
        except Exception as e:
            _logger.exception("COSTOS: Error obteniendo TC USD -> %s: %s", company_currency.name, e)
            fallback_rate = 0.0

        return {
            'rate': fallback_rate,
            'source': 'Fallback Odoo res.currency',
            'last_sync': last_sync,
        }

    @api.model
    def _get_usd_to_company_rate_for_costing(self, company=None):
        """
        Devuelve cuántas unidades de la moneda de la compañía equivalen a 1 USD.
        """
        return self._get_costing_rate_info(company=company).get('rate', 0.0)

    # ============================================================
    # ACCIONES Y CÁLCULO DE COSTOS
    # ============================================================

    def action_update_costs(self):
        """Acción manual para recalcular costos"""
        _logger.info("COSTOS: Iniciando actualización manual para %s", self.mapped('display_name'))
        self._compute_costo_all_in()
        self._calculate_escalera_precios()

    def _compute_costo_all_in(self):
        """
        Calcula el costo ALL-IN.

        Componentes:
        1. Costo base:
           - Si hay compras confirmadas: MaxAvg histórico en MXN.
           - Si no hay compras: standard_price.

        2. Logística:
           - tariff.all_in está en USD por contenedor.
           - Se divide entre x_container_capacity para obtener USD/m².
           - Se convierte a MXN usando TC Banorte venta.

        3. Arancel:
           - Se calcula sobre el costo base bruto en MXN.
        """
        company = self.env.company
        company_currency = company.currency_id
        rate_info = self._get_costing_rate_info(company=company)
        usd_to_company_rate = rate_info.get('rate', 0.0)

        for record in self:
            _logger.info("COSTOS: Calculando para producto %s (ID: %s)", record.display_name, record.id)

            record.x_cost_exchange_rate = usd_to_company_rate
            record.x_cost_exchange_rate_source = rate_info.get('source') or ''
            record.x_cost_exchange_rate_last_sync = rate_info.get('last_sync') or False

            purchase_lines = self.env['purchase.order.line'].search([
                ('product_id.product_tmpl_id', '=', record.id),
                ('state', 'in', ['purchase', 'done'])
            ], order='date_order asc, id asc')

            has_purchases = bool(purchase_lines)
            record.x_has_purchases = has_purchases

            all_in_cost_mxn = 0.0
            base_gross_cost_mxn = 0.0
            logistics_cost_mxn = 0.0
            logistics_cost_usd = 0.0
            duty_cost_mxn = 0.0
            duty_cost_usd = 0.0
            freight_tariff_all_in_usd = 0.0

            logistics_summary = "Sin cálculo logístico."
            cost_summary_lines = []

            if not has_purchases:
                base_gross_cost_mxn = record.standard_price or 0.0
                all_in_cost_mxn = base_gross_cost_mxn

                _logger.info("COSTOS: Sin compras. Usando Costo Estándar: %s", all_in_cost_mxn)

                record.x_max_avg_cost_mxn = 0.0

                logistics_summary = "Sin compras confirmadas. No se aplica logística ni arancel."

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
                    total_val_mxn += line.product_qty * price_unit_mxn

                    current_avg = total_val_mxn / total_qty

                    if current_avg > max_avg:
                        max_avg = current_avg

                base_gross_cost_mxn = max_avg
                record.x_max_avg_cost_mxn = max_avg

                if (
                    record.x_origin_country_id
                    and record.x_pol_id
                    and record.x_pod_id
                    and record.x_container_capacity > 0
                ):
                    tariff = self.env['freight.tariff'].search([
                        ('country_id', '=', record.x_origin_country_id.id),
                        ('pol_id', '=', record.x_pol_id.id),
                        ('pod_id', '=', record.x_pod_id.id),
                        ('state', '=', 'active')
                    ], order='create_date desc', limit=1)

                    if tariff:
                        freight_tariff_all_in_usd = tariff.all_in or 0.0
                        logistics_cost_usd = freight_tariff_all_in_usd / record.x_container_capacity

                        if usd_to_company_rate > 0:
                            logistics_cost_mxn = logistics_cost_usd * usd_to_company_rate
                        else:
                            logistics_cost_mxn = 0.0
                            _logger.warning(
                                "COSTOS: No se pudo calcular logística para %s porque el TC USD->%s es 0.",
                                record.display_name,
                                company_currency.name,
                            )

                        logistics_summary = (
                            f"{freight_tariff_all_in_usd:.4f} USD / "
                            f"{record.x_container_capacity:.4f} m² = "
                            f"{logistics_cost_usd:.4f} USD/m² × "
                            f"TC {usd_to_company_rate:.4f} = "
                            f"{logistics_cost_mxn:.4f} MXN/m²"
                        )

                        _logger.info(
                            "COSTOS: Logística %s | Tarifa All-In USD=%s | Capacidad=%s | "
                            "USD/m²=%s | TC=%s | Logística %s/m²=%s",
                            record.display_name,
                            freight_tariff_all_in_usd,
                            record.x_container_capacity,
                            logistics_cost_usd,
                            usd_to_company_rate,
                            company_currency.name,
                            logistics_cost_mxn,
                        )

                    else:
                        logistics_summary = "No se encontró tarifa activa para País/POL/POD."

                else:
                    logistics_summary = "Configuración logística incompleta o capacidad de contenedor inválida."

                if record.x_arancel_pct > 0:
                    duty_cost_mxn = base_gross_cost_mxn * (record.x_arancel_pct / 100.0)

                all_in_cost_mxn = base_gross_cost_mxn + logistics_cost_mxn + duty_cost_mxn

            base_gross_cost_usd = base_gross_cost_mxn / usd_to_company_rate if usd_to_company_rate > 0 else 0.0
            duty_cost_usd = duty_cost_mxn / usd_to_company_rate if usd_to_company_rate > 0 else 0.0
            all_in_cost_usd = all_in_cost_mxn / usd_to_company_rate if usd_to_company_rate > 0 else 0.0

            record.x_cost_base_mxn = base_gross_cost_mxn
            record.x_cost_base_usd = base_gross_cost_usd
            record.x_freight_tariff_all_in_usd = freight_tariff_all_in_usd
            record.x_logistics_cost_usd = logistics_cost_usd
            record.x_logistics_cost_mxn = logistics_cost_mxn
            record.x_duty_cost_usd = duty_cost_usd
            record.x_duty_cost_mxn = duty_cost_mxn
            record.x_costo_mayor_usd = all_in_cost_usd
            record.x_logistics_calc_summary = logistics_summary

            cost_summary_lines.append(
                f"TC usado: {usd_to_company_rate:.4f} MXN/USD ({rate_info.get('source') or 'Sin fuente'})"
            )
            cost_summary_lines.append(f"Logística: {logistics_summary}")
            cost_summary_lines.append(
                f"ALL-IN MXN = Base {base_gross_cost_mxn:.4f} + "
                f"Logística {logistics_cost_mxn:.4f} + "
                f"Arancel {duty_cost_mxn:.4f} = "
                f"{all_in_cost_mxn:.4f} MXN"
            )
            cost_summary_lines.append(
                f"ALL-IN USD = Base {base_gross_cost_usd:.4f} + "
                f"Logística {logistics_cost_usd:.4f} + "
                f"Arancel {duty_cost_usd:.4f} = "
                f"{all_in_cost_usd:.4f} USD"
            )

            record.x_cost_calc_summary = "\n".join(cost_summary_lines)

            if abs((record.x_costo_mayor or 0.0) - (all_in_cost_mxn or 0.0)) > 0.0001:
                record.sudo().write({
                    'x_costo_mayor': all_in_cost_mxn
                })

    def _calculate_escalera_precios(self):
        """
        Calcula la escalera de precios.

        MXN:
        - Se calcula desde el costo ALL-IN o desde precio fijo.

        USD:
        - Se divide usando TC Banorte venta.
        - Si Banorte no existe, se usa fallback Odoo.
        """
        banorte_rate = self._get_usd_to_company_rate_for_costing(self.env.company)

        def _price_from_utility(base, utility_pct):
            divisor = 1 - (utility_pct / 100.0)

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
            'x_origin_country_id',
            'x_pol_id',
            'x_pod_id',
            'x_container_capacity',
            'x_arancel_pct',
        ]

        price_triggers = [
            'x_utilidad',
            'x_utilidad_media',
            'x_utilidad_minima',
            'x_pricing_mode',
            'x_fixed_price',
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
    def _get_next_banorte_run_utc(self, now_utc=None):
        """
        Ventana local: 08:00 a 20:00 (Monterrey)
        Saltos variables: 45, 60, 75, 90 min
        Devuelve datetime UTC naive para guardar en ir_cron.nextcall.
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
        cron = self.env.ref(
            'inventory_shopping_cart.ir_cron_update_banorte_prices',
            raise_if_not_found=False
        )

        if not cron:
            _logger.warning(
                "BANORTE SYNC: No se encontró el cron "
                "inventory_shopping_cart.ir_cron_update_banorte_prices"
            )
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

        Parámetro requerido:
        - API_KEY en ir.config_parameter.

        Importante:
        - Recalcula costos ALL-IN porque la logística depende del TC Banorte.
        - Después recalcula escalera de precios.
        """
        icp = self.env['ir.config_parameter'].sudo()
        api_key = icp.get_param('API_KEY')

        if not api_key:
            _logger.warning("BANORTE SYNC: API_KEY no configurada")

            try:
                self._reschedule_banorte_cron_sql()
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception("BANORTE SYNC: error reprogramando cron sin API_KEY")

            return False

        headers = {
            "x-api-key": api_key
        }

        try:
            response = requests.get(BANORTE_API_URL, headers=headers, timeout=90)
            response.raise_for_status()

            data = response.json()
            _logger.warning("BANORTE RAW RESPONSE: %s", data)

            buy_raw = data.get("tipo-cambio-compra-banorte")
            sell_raw = data.get("tipo-cambio-venta-banorte")

            rate_buy = self._parse_money_to_float(buy_raw)
            rate_sell = self._parse_money_to_float(sell_raw)

            if rate_sell <= 0:
                raise ValueError(f"Tipo de cambio venta inválido: {sell_raw}")

            # Guardar tipo de cambio primero
            icp.set_param('banorte.last_rate', rate_sell)
            icp.set_param('banorte.last_rate_buy', rate_buy)
            icp.set_param('banorte.last_rate_sell', rate_sell)
            icp.set_param('banorte.last_payload', str(data))
            icp.set_param('banorte.last_sync_at', fields.Datetime.now())

            # Histórico si existe el modelo
            if 'banorte.rate.log' in self.env:
                self.env['banorte.rate.log'].sudo().create({
                    'requested_at': fields.Datetime.now(),
                    'rate_buy': rate_buy,
                    'rate_sell': rate_sell,
                    'raw_response': str(data),
                    'source_url': BANORTE_API_URL,
                    'success': True,
                })

            # COMMIT inmediato para que el TC quede persistido
            self.env.cr.commit()

            # Recalcular productos:
            # 1. Costo ALL-IN porque logística usa Banorte.
            # 2. Escalera de precios porque USD también usa Banorte.
            products = self.search([('active', '=', True)])
            products._compute_costo_all_in()
            products._calculate_escalera_precios()

            # Recalcular órdenes abiertas
            if 'sale.order' in self.env:
                orders = self.env['sale.order'].search([
                    ('state', 'in', ['draft', 'sent'])
                ])
                orders._compute_exchange_rate()
            else:
                orders = self.env['sale.order']

            self.env.cr.commit()

            _logger.info(
                "BANORTE SYNC OK | compra=%s venta=%s | productos recalculados=%s | ordenes recalculadas=%s",
                rate_buy,
                rate_sell,
                len(products),
                len(orders)
            )

            return True

        except Exception as e:
            self.env.cr.rollback()

            if 'banorte.rate.log' in self.env:
                try:
                    self.env['banorte.rate.log'].sudo().create({
                        'requested_at': fields.Datetime.now(),
                        'rate_buy': 0.0,
                        'rate_sell': 0.0,
                        'raw_response': '',
                        'source_url': BANORTE_API_URL,
                        'success': False,
                        'error_message': str(e),
                    })
                    self.env.cr.commit()
                except Exception:
                    self.env.cr.rollback()

            _logger.exception("BANORTE SYNC Error: %s", e)
            return False

        finally:
            try:
                self._reschedule_banorte_cron_sql()
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception("BANORTE SYNC: error reprogramando cron")

    # ============================================================
    # PRECIOS PARA FRONTEND / VALIDACIÓN
    # ============================================================

    @api.model
    def get_custom_prices(self, product_id, currency_code):
        product = self.browse(product_id)
        prices = []
        is_authorizer = self.env.user.has_group('inventory_shopping_cart.group_price_authorizer')

        if currency_code == 'USD':
            prices.append({
                'label': 'Precio  (1)',
                'value': product.x_price_usd_1,
                'level': 'high'
            })
            prices.append({
                'label': 'Precio  (2)',
                'value': product.x_price_usd_2,
                'level': 'medium'
            })

            if is_authorizer:
                prices.append({
                    'label': 'Precio  (3)',
                    'value': product.x_price_usd_3,
                    'level': 'minimum'
                })

        else:
            prices.append({
                'label': 'Precio  (1)',
                'value': product.x_price_mxn_1,
                'level': 'high'
            })
            prices.append({
                'label': 'Precio  (2)',
                'value': product.x_price_mxn_2,
                'level': 'medium'
            })

            if is_authorizer:
                prices.append({
                    'label': 'Precio  (3)',
                    'value': product.x_price_mxn_3,
                    'level': 'minimum'
                })

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
            return {
                'needs_authorization': False,
                'products': [],
                'is_authorizer': True
            }

        needs_auth = []
        is_seller = self.env.user.has_group('inventory_shopping_cart.group_seller')

        if not is_seller:
            return {
                'needs_authorization': False,
                'products': []
            }

        for product_id_str, requested_price in product_prices.items():
            product = self.browse(int(product_id_str))

            medium = product.x_price_mxn_2 if currency_code == 'MXN' else product.x_price_usd_2

            if requested_price < (medium - 0.01):
                needs_auth.append({
                    'product_id': int(product_id_str),
                    'product_name': product.display_name,
                    'requested_price': requested_price,
                    'medium_price': medium,
                    'minimum_price': product.x_price_mxn_3 if currency_code == 'MXN' else product.x_price_usd_3,
                })

        return {
            'needs_authorization': len(needs_auth) > 0,
            'products': needs_auth
        }


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        res = super(ProductProduct, self).write(vals)

        if 'standard_price' in vals:
            for product in self:
                product.product_tmpl_id._compute_costo_all_in()
                product.product_tmpl_id._calculate_escalera_precios()

        return res