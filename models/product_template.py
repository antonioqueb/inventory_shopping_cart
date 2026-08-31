# ./models/product_template.py
# -*- coding: utf-8 -*-
import math
import requests
import logging
import random
import re
from datetime import datetime, timedelta, time

from markupsafe import Markup

from odoo import models, fields, api
from odoo.exceptions import ValidationError

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

_logger = logging.getLogger(__name__)



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

    x_naviera_id = fields.Many2one(
        'res.partner', string='Naviera (costeo)',
        help="Naviera de la recepción MÁS COSTOSA registrada. Selecciona la "
             "tarifa correcta del tarifario para el costeo.",
    )
    x_forwarder_id = fields.Many2one(
        'res.partner', string='Forwarder (costeo)',
        help="Forwarder de la recepción más costosa registrada.",
    )

    # === TIPO DE CAMBIO USADO PARA COSTEO ===

    x_cost_eur_usd_rate = fields.Float(
        string='TC Costeo EUR → USD',
        digits=(12, 6),
        readonly=True,
        help="Tipo de cambio EUR→USD (Banco Central Europeo) usado cuando la "
             "compra es en euros: primero EUR→USD, después USD→MXN (Banorte).",
    )
    x_cost_eur_usd_source = fields.Char(
        string='Fuente TC EUR→USD',
        readonly=True,
    )

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
       help="Calculado: Precio = Costo / (1 - %Utilidad), utilidad sobre el PRECIO. "
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

    # Proxy checkbox del modo de precio para la mesa Costos y Precios:
    # palomeado = Precio Fijo (x_pricing_mode='fixed'). El inverse escribe
    # x_pricing_mode vía write(), así que el recálculo automático de la
    # escalera se dispara solo (price_triggers).
    x_is_fixed_price = fields.Boolean(
        string='Precio fijo',
        compute='_compute_x_is_fixed_price',
        inverse='_inverse_x_is_fixed_price',
        help='Palomeado: el precio parte del Precio Fijo base y las '
             'utilidades bajan como niveles de descuento. Sin palomear: '
             'precio calculado = costo all-in + utilidad.',
    )

    @api.depends('x_pricing_mode')
    def _compute_x_is_fixed_price(self):
        for rec in self:
            rec.x_is_fixed_price = rec.x_pricing_mode == 'fixed'

    def _inverse_x_is_fixed_price(self):
        for rec in self:
            rec.x_pricing_mode = 'fixed' if rec.x_is_fixed_price \
                else 'calculated'

    # === ESTRATEGIA DE PRECIOS: UTILIDADES DIRECTAS ===

    x_utilidad = fields.Float(
        string='% Utilidad Alta',
        default=40.0,
        help="Margen de utilidad para el Precio Alto (Nivel 1). Precio = Costo / (1 - %), utilidad sobre el precio."
    )

    x_utilidad_media = fields.Float(
        string='% Utilidad Media',
        default=35.0,
        help="Margen de utilidad para el Precio Medio (Nivel 2). Precio = Costo / (1 - %), utilidad sobre el precio."
    )

    x_utilidad_minima = fields.Float(
        string='% Utilidad Nivel 3',
        default=30.0,
        help="Margen de utilidad para el Precio Nivel 3. Precio = Costo / (1 - %), utilidad sobre el precio."
    )

    x_utilidad_4 = fields.Float(
        string='% Utilidad Nivel 4',
        default=25.0,
        help="Margen de utilidad para el Precio Nivel 4. Visible solo para vendedores mayoristas y autorizadores. "
             "Precio = Costo / (1 - %), utilidad sobre el precio."
    )

    x_utilidad_5 = fields.Float(
        string='% Utilidad Mínima (Nivel 5)',
        default=20.0,
        help="Margen de utilidad para el Precio Mínimo (Nivel 5). Visible solo para autorizadores. "
             "Precio = Costo / (1 - %), utilidad sobre el precio."
    )

    _UTILIDAD_FIELDS = (
        'x_utilidad', 'x_utilidad_media', 'x_utilidad_minima',
        'x_utilidad_4', 'x_utilidad_5',
    )

    @api.constrains('x_utilidad', 'x_utilidad_media', 'x_utilidad_minima',
                    'x_utilidad_4', 'x_utilidad_5')
    def _check_utilidad_range(self):
        """La utilidad es SOBRE EL COSTO y debe vivir en [0, 100):
        100% (duplicar el costo) se reserva como tope prohibido por
        pedido explícito, y los negativos venderían bajo costo."""
        for rec in self:
            for fname in self._UTILIDAD_FIELDS:
                val = rec[fname] or 0.0
                if val < 0 or val >= 100:
                    raise ValidationError(
                        'La utilidad "%s" debe ser mayor o igual a 0%% y '
                        'MENOR a 100%% (capturaste %.2f%%).' % (
                            rec._fields[fname].string or fname, val))

    # MARKUP equivalente SOBRE EL COSTO (solo lectura, referencia):
    # markup = margen / (100 - margen). El % que MANDA es el margen sobre
    # el precio (x_utilidad*); esto solo traduce: margen 40% ≡ markup 66.7%.
    x_markup_1 = fields.Float(
        string='Markup s/costo N1', compute='_compute_x_markup', digits=(6, 1))
    x_markup_2 = fields.Float(
        string='Markup s/costo N2', compute='_compute_x_markup', digits=(6, 1))
    x_markup_3 = fields.Float(
        string='Markup s/costo N3', compute='_compute_x_markup', digits=(6, 1))
    x_markup_4 = fields.Float(
        string='Markup s/costo N4', compute='_compute_x_markup', digits=(6, 1))
    x_markup_5 = fields.Float(
        string='Markup s/costo N5', compute='_compute_x_markup', digits=(6, 1))

    @api.depends('x_utilidad', 'x_utilidad_media', 'x_utilidad_minima',
                 'x_utilidad_4', 'x_utilidad_5')
    def _compute_x_markup(self):
        def markup(margen):
            margen = margen or 0.0
            if margen <= 0 or margen >= 100:
                return 0.0
            return margen / (100.0 - margen) * 100.0
        for rec in self:
            rec.x_markup_1 = markup(rec.x_utilidad)
            rec.x_markup_2 = markup(rec.x_utilidad_media)
            rec.x_markup_3 = markup(rec.x_utilidad_minima)
            rec.x_markup_4 = markup(rec.x_utilidad_4)
            rec.x_markup_5 = markup(rec.x_utilidad_5)

    # === CAMPOS DE PRECIOS CALCULADOS ===

    # === COSTO EDITABLE EN LA LISTA + UTILIDAD POR NIVEL ===
    # Solo visibles/editables para el grupo "Ver Costo de Productos"
    # (la vista de lista está restringida por groups_id). Editar el USD
    # recalcula el MXN con el TC de costeo y viceversa; las utilidades
    # por nivel se recalculan en vivo en la misma fila.
    x_cost_reviewed = fields.Boolean(
        string='Revisado',
        default=False,
        copy=False,
        help='Marca de la mesa Costos y Precios: costo y precios de este '
             'producto ya fueron revisados y están bien (estrella).',
    )

    x_costo_usd_edit = fields.Float(
        string='Costo base USD',
        digits='Product Price',
        compute='_compute_som_costo_edit',
        inverse='_inverse_som_costo_usd',
        help='Costo BASE en USD. Editable: al guardar escribe el costo '
             'nativo (standard_price = USD × TC de costeo) y corre el '
             'motor ALL-IN (base + logística + arancel).',
    )
    x_costo_mxn_edit = fields.Float(
        string='Costo base MXN',
        digits='Product Price',
        compute='_compute_som_costo_edit',
        inverse='_inverse_som_costo_mxn',
        help='Costo BASE en MXN (el costo nativo standard_price). '
             'Editable: al guardar corre el motor ALL-IN completo.',
    )
    def _som_costing_rate(self):
        try:
            info = self._get_costing_rate_info(company=self.env.company)
            return float(info.get('rate') or 0.0)
        except Exception:
            return 0.0

    @api.depends('standard_price')
    def _compute_som_costo_edit(self):
        """Muestra el costo BASE nativo (standard_price) en MXN y USD."""
        rate = self._som_costing_rate()
        for rec in self:
            rec.x_costo_mxn_edit = rec.standard_price or 0.0
            rec.x_costo_usd_edit = (
                (rec.standard_price or 0.0) / rate) if rate else 0.0

    def _inverse_som_costo_usd(self):
        """USD capturado → standard_price (nativo). El write de
        standard_price dispara el motor completo: costo ALL-IN y
        escalera de precios MXN/USD 1-5."""
        rate = self._som_costing_rate()
        for rec in self:
            if rate:
                rec.standard_price = (rec.x_costo_usd_edit or 0.0) * rate

    def _inverse_som_costo_mxn(self):
        """MXN capturado → standard_price (nativo) → motor completo."""
        for rec in self:
            rec.standard_price = rec.x_costo_mxn_edit or 0.0


    x_price_usd_1 = fields.Float(string='Precio USD 1', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_2 = fields.Float(string='Precio USD 2', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_3 = fields.Float(string='Precio USD 3', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_4 = fields.Float(string='Precio USD 4', digits='Product Price', default=0.0, company_dependent=True)
    x_price_usd_5 = fields.Float(string='Precio USD 5', digits='Product Price', default=0.0, company_dependent=True)

    x_price_mxn_1 = fields.Float(string='Precio MXN 1', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_2 = fields.Float(string='Precio MXN 2', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_3 = fields.Float(string='Precio MXN 3', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_4 = fields.Float(string='Precio MXN 4', digits='Product Price', default=0.0, company_dependent=True)
    x_price_mxn_5 = fields.Float(string='Precio MXN 5', digits='Product Price', default=0.0, company_dependent=True)

    x_name_sps = fields.Char(
        string='Nombre SPS',
        help='Nombre del producto en el sistema SPS',
        default=''
    )

    # Visibilidad de la ESCALERA por rol. El `groups=` de la vista no basta:
    # un "Vendedor con Precios Limitados" que además traiga el Visor del
    # Dashboard pertenece al grupo y vería 3/4/5. Estos flags reusan
    # _get_user_price_role(), que sí aplica el tope duro del vendedor
    # limitado, para que la escalera diga lo mismo que el selector y el
    # tooltip del Inventario Visual.
    x_som_can_see_level_3 = fields.Boolean(
        string='Puede ver Precio 3',
        compute='_compute_som_price_level_visibility',
        help='Precio 3 abierto a toda la fuerza de ventas (política 31 ago 2026).',
    )
    x_som_can_see_level_3_4 = fields.Boolean(
        string='Ve Precios 3 y 4',
        compute='_compute_som_price_level_visibility',
        help='Técnico: mayorista, autorizador o visor del Dashboard.',
    )
    x_som_can_see_level_5 = fields.Boolean(
        string='Ve Precio 5',
        compute='_compute_som_price_level_visibility',
        help='Técnico: solo autorizador de precios y visor del Dashboard.',
    )

    @api.depends_context('uid')
    def _compute_som_price_level_visibility(self):
        levels = self._get_user_visible_price_levels()
        can_3 = 'minimum' in levels
        can_3_4 = 'level_4' in levels
        can_5 = 'level_5' in levels
        for rec in self:
            rec.x_som_can_see_level_3 = can_3
            rec.x_som_can_see_level_3_4 = can_3_4
            rec.x_som_can_see_level_5 = can_5

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
    def _get_eur_to_usd_rate_for_costing(self):
        """EUR→USD para costeo. El DOF solo publica el dólar, así que la
        fuente del euro es el BANCO CENTRAL EUROPEO (frankfurter.app, sin
        llave). La última tasa buena se cachea en ir.config_parameter; si el
        servicio no responde se usa el caché y, en último caso, res.currency.
        Flujo cuando la compra es en EUR: EUR→USD (BCE) → USD→MXN (Banorte)."""
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            resp = requests.get(
                "https://api.frankfurter.app/latest?from=EUR&to=USD",
                timeout=15,
            )
            rate = float(resp.json()['rates']['USD'])
            if rate > 0:
                ICP.set_param('som_costing.eur_usd_rate', str(rate))
                ICP.set_param('som_costing.eur_usd_source',
                              'BCE (frankfurter.app) %s' % resp.json().get('date', ''))
                return rate, ICP.get_param('som_costing.eur_usd_source')
        except Exception as e:
            _logger.warning("COSTOS: BCE EUR→USD no disponible (%s); usando caché.", e)

        cached = float(ICP.get_param('som_costing.eur_usd_rate', '0') or 0)
        if cached > 0:
            return cached, (ICP.get_param('som_costing.eur_usd_source', '') or '') + ' [caché]'

        try:
            eur = self.env.ref('base.EUR')
            usd = self.env.ref('base.USD')
            rate = eur._convert(1.0, usd, self.env.company, fields.Date.today())
            return rate, 'Fallback Odoo res.currency'
        except Exception:
            return 0.0, 'Sin fuente'

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

    @api.model
    def _som_current_logistics_mxn(self, record, usd_to_company_rate):
        """Logística VIGENTE por m² en MXN para un producto (espejo del
        bloque de flete de _compute_costo_all_in, solo la cifra, sin
        resúmenes ni compuertas). Se usa para descontarla de la SEMILLA:
        el costo migrado (SPS) ya venía entregado (logística incluida) y
        sin este descuento se duplicaba al sumarla de nuevo en el ALL-IN.
        Devuelve 0.0 si falta configuración o tarifa."""
        try:
            freight_mode = getattr(record, 'x_freight_mode', False) or 'international'
            if freight_mode == 'national':
                nat = getattr(record, 'x_national_route_id', False)
                if not nat or not nat.active:
                    return 0.0
                cap = (nat.capacidad or 0.0) or (record.x_container_capacity or 0.0)
                if cap <= 1.0:
                    return 0.0
                return (nat.costo or 0.0) / cap
            if not (record.x_origin_country_id and record.x_pol_id
                    and record.x_pod_id
                    and (record.x_container_capacity or 0.0) > 1.0
                    and usd_to_company_rate > 0):
                return 0.0
            candidates = self.env['freight.tariff'].search([
                ('country_id', '=', record.x_origin_country_id.id),
                ('pol_id', '=', record.x_pol_id.id),
                ('pod_id', '=', record.x_pod_id.id),
                ('state', '=', 'active'),
            ], order='create_date desc')
            tariff = candidates[:1]
            if 'x_naviera_id' in record._fields and record.x_naviera_id:
                nav = candidates.filtered(lambda t: t.naviera_id == record.x_naviera_id)
                if record.x_forwarder_id:
                    navf = nav.filtered(lambda t: t.forwarder_id == record.x_forwarder_id)
                    nav = navf or nav
                tariff = nav[:1] or tariff
            if not tariff:
                return 0.0
            return (tariff.all_in or 0.0) / record.x_container_capacity * usd_to_company_rate
        except Exception:
            _logger.exception('COSTOS: no se pudo estimar la logística de la semilla para %s', record.display_name)
            return 0.0

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
        eur_usd_rate, eur_usd_source = self._get_eur_to_usd_rate_for_costing()
        eur_currency = self.env.ref('base.EUR', raise_if_not_found=False)
        usd_to_company_rate = rate_info.get('rate', 0.0)

        for record in self:
            _logger.info("COSTOS: Calculando para producto %s (ID: %s)", record.display_name, record.id)

            record.x_cost_exchange_rate = usd_to_company_rate
            record.x_cost_exchange_rate_source = rate_info.get('source') or ''
            record.x_cost_exchange_rate_last_sync = rate_info.get('last_sync') or False

            # Multiempresa: el costo (company_dependent) se calcula con las
            # compras de LA compañía en curso (env.company = with_company).
            po_line_domain = [
                ('product_id.product_tmpl_id', '=', record.id),
                ('state', 'in', ['purchase', 'done']),
                ('company_id', '=', company.id),
            ]
            # Solo compras ACTIVADAS (publicadas o recibidas) mueven el
            # promedio: una OC confirmada sin publicar/recibir es invisible
            # para el costeo, sin importar quién dispare el recálculo.
            POLine = self.env['purchase.order.line']
            if 'som_costing_activated' in POLine._fields:
                po_line_domain.append(('som_costing_activated', '=', True))
            purchase_lines = POLine.search(
                po_line_domain, order='date_order asc, id asc')

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
                used_eur = False

                # ═══ SEMILLA: LA CARGA INICIAL ES EL PRIMER PUNTO DE LA SERIE ═══
                # El costo migrado (SPS) vive en el costo estándar, NO en una
                # compra: sin esta semilla, la primera compra real barata
                # desplomaba el costo porque el MaxAvg arrancaba con un solo
                # punto (el hueco CRISTALLO: estándar 5,865.72 ignorado y la
                # serie nacía en 3,430). Se siembra costo estándar × m²
                # migrados (entradas por ajuste de inventario anteriores a la
                # primera compra activada); si no hay ajustes, con el peso de
                # la primera compra (promedio parejo).
                seed_cost = record.standard_price or 0.0
                # El costo migrado YA incluye la logística (SPS costeaba
                # ENTREGADO): con compras aplicadas se le descuenta la
                # logística VIGENTE por m² para sembrar un costo BASE
                # comparable con las compras — la logística se suma UNA
                # sola vez al final del ALL-IN. Sin compras no aplica
                # (el estándar se usa tal cual y no se suma logística).
                seed_logistics = self._som_current_logistics_mxn(
                    record, usd_to_company_rate)
                seed_cost_gross = seed_cost
                if seed_logistics > 0 and seed_cost > seed_logistics:
                    seed_cost -= seed_logistics
                if seed_cost > 0:
                    first_line = purchase_lines[0]
                    first_date = first_line.order_id.date_approve or first_line.order_id.date_order
                    seed_qty = 0.0
                    try:
                        groups = self.env['stock.move.line'].sudo()._read_group(
                            [('product_id.product_tmpl_id', '=', record.id),
                             ('state', '=', 'done'),
                             ('company_id', '=', company.id),
                             ('location_id.usage', '=', 'inventory'),
                             ('location_dest_id.usage', '=', 'internal')]
                            + ([('date', '<', first_date)] if first_date else []),
                            [], ['quantity:sum'])
                        seed_qty = groups[0][0] or 0.0 if groups else 0.0
                    except Exception:
                        _logger.exception('COSTOS: no se pudo medir la carga inicial de %s', record.display_name)
                    if seed_qty <= 0:
                        seed_qty = sum(purchase_lines[:1].mapped('product_qty')) or 1.0
                    total_qty = seed_qty
                    total_val_mxn = seed_qty * seed_cost
                    max_avg = seed_cost
                    if seed_logistics > 0 and seed_cost_gross > seed_logistics:
                        cost_summary_lines.append(
                            f"• Carga inicial (semilla): {seed_qty:,.2f} × ${seed_cost:,.2f} MXN "
                            f"(estándar migrado ${seed_cost_gross:,.2f} − logística vigente ${seed_logistics:,.2f})")
                    else:
                        cost_summary_lines.append(
                            f"• Carga inicial (semilla): {seed_qty:,.2f} × ${seed_cost:,.2f} MXN (costo estándar migrado)")

                for line in purchase_lines:
                    if line.product_qty <= 0:
                        continue

                    line_currency = line.currency_id
                    rate_date = line.order_id.date_approve or line.order_id.date_order or fields.Date.today()

                    price_unit_mxn = line.price_unit

                    if (
                        eur_currency and line_currency == eur_currency
                        and eur_usd_rate > 0 and usd_to_company_rate > 0
                    ):
                        # Compra en EUROS: flujo explícito EUR→USD (BCE) y
                        # después USD→MXN (Banorte), igual que el resto del
                        # costeo en dólares.
                        price_unit_mxn = line.price_unit * eur_usd_rate * usd_to_company_rate
                        used_eur = True
                    elif line_currency != company_currency:
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

                # ═══ MODO DE FLETE ═══
                # NACIONAL: costo MXN directo del Tarifario Nacional dividido
                # entre la capacidad del viaje (o la del producto). Sin
                # arancel (flete doméstico) y sin conversión de divisa.
                freight_mode = getattr(record, 'x_freight_mode', False) \
                    or 'international'
                if freight_mode == 'national':
                    nat = getattr(record, 'x_national_route_id', False)
                    missing_nat = []
                    if not nat or not nat.active:
                        missing_nat.append(
                            'ruta nacional ACTIVA (Tarifario Nacional)')
                    cap_nat = 0.0
                    if nat:
                        cap_nat = (nat.capacidad or 0.0) \
                            or (record.x_container_capacity or 0.0)
                    if cap_nat <= 1.0:
                        missing_nat.append(
                            'capacidad (> 1 m²) en la ruta nacional o el '
                            'producto')
                    if missing_nat:
                        msg = (
                            "⛔ CÁLCULO OMITIDO — faltan parámetros: %s. El "
                            "costo conserva el último valor válido "
                            "($%.2f MXN)." % (
                                ', '.join(missing_nat),
                                record.x_costo_mayor or 0.0)
                        )
                        record.x_logistics_calc_summary = msg
                        record.x_cost_calc_summary = msg
                        continue

                    costo_nat = nat.costo or 0.0
                    logistics_cost_mxn = costo_nat / cap_nat
                    if usd_to_company_rate > 0:
                        logistics_cost_usd = (
                            logistics_cost_mxn / usd_to_company_rate)
                        freight_tariff_all_in_usd = (
                            costo_nat / usd_to_company_rate)
                    logistics_summary = (
                        f"NACIONAL {nat.display_name}: {costo_nat:.2f} MXN / "
                        f"{cap_nat:.2f} m² = {logistics_cost_mxn:.4f} MXN/m² "
                        f"(flete doméstico: sin arancel ni TC)")
                    duty_cost_mxn = 0.0
                    all_in_cost_mxn = base_gross_cost_mxn + logistics_cost_mxn
                else:
                    # ═══ COMPUERTA DE PARÁMETROS (regla de negocio) ═══
                    # Con compras confirmadas, el ALL-IN exige la configuración
                    # logística COMPLETA y una tarifa activa. Si falta algo, NO se
                    # intenta el cálculo (nada de costos con logística en $0):
                    # el costo conserva su último valor válido y el resumen
                    # explica exactamente qué falta.
                    missing_params = []
                    if not record.x_origin_country_id:
                        missing_params.append('país de origen')
                    if not record.x_pol_id:
                        missing_params.append('puerto de carga (POL)')
                    if not record.x_pod_id:
                        missing_params.append('puerto destino (POD)')
                    if (record.x_container_capacity or 0.0) <= 1.0:
                        missing_params.append('capacidad de contenedor (> 1 m²)')

                    gate_tariff = None
                    if not missing_params:
                        gate_tariff = self.env['freight.tariff'].search([
                            ('country_id', '=', record.x_origin_country_id.id),
                            ('pol_id', '=', record.x_pol_id.id),
                            ('pod_id', '=', record.x_pod_id.id),
                            ('state', '=', 'active'),
                        ], limit=1)

                    if missing_params or not gate_tariff:
                        reason = (
                            'faltan parámetros: ' + ', '.join(missing_params)
                            if missing_params
                            else 'no hay tarifa ACTIVA en el tarifario para País/POL/POD'
                        )
                        msg = (
                            "⛔ CÁLCULO OMITIDO — %s. El costo conserva el último "
                            "valor válido ($%.2f MXN)." % (
                                reason, record.x_costo_mayor or 0.0)
                        )
                        # Silencioso a propósito: un parámetro faltante NO es un
                        # intento de cálculo — nada de ruido en el log.
                        record.x_logistics_calc_summary = msg
                        record.x_cost_calc_summary = msg
                        continue

                    if (
                        record.x_origin_country_id
                        and record.x_pol_id
                        and record.x_pod_id
                        and record.x_container_capacity > 0
                    ):
                        candidates = self.env['freight.tariff'].search([
                            ('country_id', '=', record.x_origin_country_id.id),
                            ('pol_id', '=', record.x_pol_id.id),
                            ('pod_id', '=', record.x_pod_id.id),
                            ('state', '=', 'active')
                        ], order='create_date desc')
                        # Tarifa de la NAVIERA registrada (la más costosa recibida);
                        # fallback a la más reciente de la ruta si no hay match.
                        tariff = candidates[:1]
                        if 'x_naviera_id' in record._fields and record.x_naviera_id:
                            nav = candidates.filtered(
                                lambda t: t.naviera_id == record.x_naviera_id)
                            if record.x_forwarder_id:
                                navf = nav.filtered(
                                    lambda t: t.forwarder_id == record.x_forwarder_id)
                                nav = navf or nav
                            tariff = nav[:1] or tariff

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

            if has_purchases and used_eur:
                record.x_cost_eur_usd_rate = eur_usd_rate
                record.x_cost_eur_usd_source = eur_usd_source
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
                old_cost = record.x_costo_mayor or 0.0
                record.sudo().write({
                    'x_costo_mayor': all_in_cost_mxn
                })
                # HISTÓRICO DE COSTOS: cada cambio real del ALL-IN queda en el
                # chatter del producto con su contexto completo (ruta, naviera,
                # forwarder, capacidad, arancel, TC). Nunca bloquea el cálculo.
                # Solo cambios >= 1 centavo generan entrada en el histórico
                # (recalculos con diferencias de fracciones de centavo son
                # ruido de redondeo, no evolución real del costo).
                if isinstance(record.id, int) and abs(all_in_cost_mxn - old_cost) >= 0.01:
                    try:
                        delta = all_in_cost_mxn - old_cost
                        arrow = '📈' if delta > 0 else '📉'
                        ctx_lines = [
                            f"<b>{arrow} Costo ALL-IN actualizado:</b> "
                            f"${old_cost:,.2f} → <b>${all_in_cost_mxn:,.2f} MXN</b> "
                            f"({'+' if delta > 0 else ''}{delta:,.2f})",
                            f"• Costo base (MaxAvg compras): ${base_gross_cost_mxn:,.2f} MXN",
                            f"• Logística: ${logistics_cost_mxn:,.2f} MXN · "
                            f"Arancel: ${duty_cost_mxn:,.2f} MXN "
                            f"({record.x_arancel_pct:g}%)",
                        ]
                        route_bits = []
                        if record.x_origin_country_id:
                            route_bits.append(record.x_origin_country_id.name)
                        if record.x_pol_id:
                            route_bits.append(record.x_pol_id.name)
                        if record.x_pod_id:
                            route_bits.append(record.x_pod_id.name)
                        if route_bits:
                            ctx_lines.append("• Ruta: " + " → ".join(route_bits))
                        carrier_bits = []
                        if getattr(record, 'x_naviera_id', False) and record.x_naviera_id:
                            carrier_bits.append(f"Naviera: {record.x_naviera_id.name}")
                        if getattr(record, 'x_forwarder_id', False) and record.x_forwarder_id:
                            carrier_bits.append(f"Forwarder: {record.x_forwarder_id.name}")
                        if carrier_bits:
                            ctx_lines.append("• " + " · ".join(carrier_bits))
                        ctx_lines.append(
                            f"• Capacidad contenedor: {record.x_container_capacity:g} m² · "
                            f"Tarifa All-In: ${freight_tariff_all_in_usd:,.2f} USD · "
                            f"TC {usd_to_company_rate:,.4f}"
                        )
                        record.sudo().message_post(
                            body=Markup("<br/>".join(ctx_lines)),
                            message_type='comment',
                            subtype_xmlid='mail.mt_note',
                        )
                    except Exception:
                        _logger.exception(
                            "COSTOS: no se pudo registrar el histórico en el "
                            "chatter de %s.", record.display_name,
                        )

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
            # MARGEN SOBRE EL PRECIO (fórmula oficial del negocio):
            # Precio = Costo / (1 - %). El % capturado es la utilidad como
            # proporción del PRECIO de venta. El caso 100% (divisor 0) es
            # matemáticamente imposible y lo bloquea _check_utilidad_range
            # ANTES de llegar aquí; el recorte del divisor queda solo como
            # red de seguridad para datos históricos.
            divisor = 1 - ((utility_pct or 0.0) / 100.0)
            if divisor <= 0:
                divisor = 0.01
            return math.ceil(base / divisor)

        for record in self:
            mxn_1 = 0
            mxn_2 = 0
            mxn_3 = 0
            mxn_4 = 0
            mxn_5 = 0

            if record.x_pricing_mode == 'fixed' and record.x_fixed_price > 0:
                base = record.x_fixed_price
            else:
                base = record.x_costo_mayor

            if base > 0:
                mxn_1 = _price_from_utility(base, record.x_utilidad)
                mxn_2 = _price_from_utility(base, record.x_utilidad_media)
                mxn_3 = _price_from_utility(base, record.x_utilidad_minima)
                mxn_4 = _price_from_utility(base, record.x_utilidad_4)
                mxn_5 = _price_from_utility(base, record.x_utilidad_5)

            usd_1 = math.ceil(mxn_1 / banorte_rate) if banorte_rate > 0 else 0
            usd_2 = math.ceil(mxn_2 / banorte_rate) if banorte_rate > 0 else 0
            usd_3 = math.ceil(mxn_3 / banorte_rate) if banorte_rate > 0 else 0
            usd_4 = math.ceil(mxn_4 / banorte_rate) if banorte_rate > 0 else 0
            usd_5 = math.ceil(mxn_5 / banorte_rate) if banorte_rate > 0 else 0

            record.sudo().write({
                'x_price_mxn_1': mxn_1,
                'x_price_mxn_2': mxn_2,
                'x_price_mxn_3': mxn_3,
                'x_price_mxn_4': mxn_4,
                'x_price_mxn_5': mxn_5,
                'x_price_usd_1': usd_1,
                'x_price_usd_2': usd_2,
                'x_price_usd_3': usd_3,
                'x_price_usd_4': usd_4,
                'x_price_usd_5': usd_5,
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
            # Modo nacional (campos de logistica_tarifario)
            'x_freight_mode',
            'x_national_route_id',
        ]

        price_triggers = [
            'x_utilidad',
            'x_utilidad_media',
            'x_utilidad_minima',
            'x_utilidad_4',
            'x_utilidad_5',
            'x_pricing_mode',
            'x_fixed_price',
        ]

        # skip_costing_recompute: los flujos de datos (propagación desde la
        # OC, actualización al publicar/recibir) escriben estos campos SIN
        # disparar el recálculo aquí — ellos deciden el momento (regla de
        # negocio: el costo cambia SOLO al publicar o al recibir).
        if self.env.context.get('skip_costing_recompute'):
            return res

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
    def recalculate_all_costs(self):
        """RECÁLCULO MASIVO de todo el catálogo: costo ALL-IN (MaxAvg con la
        carga inicial como semilla) y escalera de precios, POR COMPAÑÍA
        (los campos son company_dependent). La compañía en curso va al
        ÚLTIMO para que los campos de resumen no dependientes de compañía
        queden con sus valores. Lo usan el cron Banorte y la migración al
        actualizar el módulo; también sirve a demanda:
        env['product.template'].recalculate_all_costs()."""
        products = self.search([('active', '=', True)])
        companies = self.env['res.company'].sudo().search([])
        companies = (companies - self.env.company) | self.env.company
        for company in companies:
            products_c = products.with_company(company)
            products_c._compute_costo_all_in()
            products_c._calculate_escalera_precios()
        _logger.info("COSTOS: recálculo masivo de %s productos en %s compañías.",
                     len(products), len(companies))
        return products

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
        # La URL del scraper vive ÚNICAMENTE en el parámetro de sistema
        # 'banorte.api_url' — sin respaldo hardcodeado: si falta, el sync
        # no corre y queda avisado en el log.
        api_url = (icp.get_param('banorte.api_url') or '').strip()
        if api_url and not api_url.endswith('/'):
            api_url += '/'
        # Llave: 'banorte.api_key' es el nombre nuevo; 'API_KEY' se conserva
        # por compatibilidad con lo ya configurado.
        api_key = icp.get_param('banorte.api_key') or icp.get_param('API_KEY')

        if not api_url:
            _logger.warning(
                "BANORTE SYNC: parámetro de sistema 'banorte.api_url' no "
                "configurado — el tipo de cambio NO se actualizará hasta "
                "definirlo (Ajustes > Técnico > Parámetros del sistema)."
            )

            try:
                self._reschedule_banorte_cron_sql()
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception("BANORTE SYNC: error reprogramando cron sin URL")

            return False

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
            response = requests.get(api_url, headers=headers, timeout=90)
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
                    'source_url': api_url,
                    'success': True,
                })

            # COMMIT inmediato para que el TC quede persistido
            self.env.cr.commit()

            # Recalcular productos:
            # 1. Costo ALL-IN porque logística usa Banorte.
            # 2. Escalera de precios porque USD también usa Banorte.
            # Multiempresa: costo ALL-IN y escalera son company_dependent →
            # se recalculan POR compañía (with_company). La compañía del
            # cron (la principal) va al ÚLTIMO para que los campos de
            # resumen NO dependientes de compañía (TC de costeo, USD,
            # resúmenes) queden como hoy: los de la compañía principal.
            products = self.recalculate_all_costs()

            # Recalcular órdenes abiertas (cron = superusuario, sin reglas:
            # trae todas las compañías; el TC sale de la de cada orden).
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
                        'source_url': api_url,
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
    def _get_user_price_role(self, user=None):
        """
        Identifica el rol comercial del usuario para la escalera de precios.
        Con `user` evalúa a ESE usuario (p. ej. el vendedor de la orden);
        sin él, al usuario actual.

        Retorna uno de: 'authorizer', 'mayorista', 'seller', 'none'.

        PRECEDENCIA (15 ago 2026 — se reportaron vendedores limitados
        viendo los 5 niveles):

        1. Autorizador de Precios Mínimos: manda siempre. Tiene que ver el
           piso absoluto para poder autorizar.
        2. "Vendedor con Precios Limitados" (group_seller SIN mayorista) es
           un TOPE DURO: 2 niveles en todos lados, aunque además traiga el
           Visor del Dashboard. Antes el visor lo promovía a 'authorizer' y
           el vendedor terminaba viendo la escalera completa —y saltándose
           los candados de precio— con solo tener el dashboard prendido.
        3. Visor del Dashboard sin nivel de vendedor: dirección, ve 1-5.
        4. Mayorista: 1-4.
        """
        user = user or self.env.user
        if user.has_group('inventory_shopping_cart.group_price_authorizer'):
            return 'authorizer'

        is_mayorista = user.has_group(
            'inventory_shopping_cart.group_seller_mayorista')
        # OJO: group_seller_mayorista IMPLICA group_seller, por eso el
        # "limitado" se define como seller Y NO mayorista.
        if user.has_group('inventory_shopping_cart.group_seller') \
                and not is_mayorista:
            return 'seller'

        # Visor del Dashboard Personalizado: nivel dirección — opera
        # precios sin solicitar autorización (mismo trato que el
        # autorizador para la escalera y los candados de precio).
        if user.has_group('inventory_shopping_cart.group_dashboard_viewer'):
            return 'authorizer'
        if is_mayorista:
            return 'mayorista'
        return 'none'

    @api.model
    def _som_user_is_price_exempt(self, user=None):
        """Visor del Dashboard Personalizado: perfil dirección para el
        CANDADO de precios — sus órdenes NUNCA se bloquean por precio bajo
        ni disparan el flujo de autorización (puede imprimir, confirmar y
        enviar con cualquier precio, y no ve el botón de solicitar
        autorización porque su orden jamás se marca).

        OJO: esto NO toca el rol de la escalera (_get_user_price_role):
        el tope de VISIBILIDAD del 15 ago para vendedor limitado + visor
        sigue igual (ve 2 niveles). Tampoco lo vuelve autorizador: aprobar
        solicitudes de terceros sigue siendo del grupo Autorizador."""
        user = user or self.env.user
        return user.has_group(
            'inventory_shopping_cart.group_dashboard_viewer')

    @api.model
    def _get_user_visible_price_levels(self):
        """
        Devuelve la lista de niveles ('high', 'medium', 'minimum', 'level_4', 'level_5')
        que el usuario actual puede ver en los selectores.

        - Vendedor regular: 1-2.
        - Vendedor mayorista: 1-4 (el Precio 5 es el piso absoluto y NO se le
          muestra; para bajar de ahí pide autorización).
        - Autorizador y visor del Dashboard: 1-5.
        """
        role = self._get_user_price_role()
        if role == 'authorizer':
            return ['high', 'medium', 'minimum', 'level_4', 'level_5']
        if role == 'mayorista':
            return ['high', 'medium', 'minimum', 'level_4']
        # Política 31 ago 2026: el Precio 3 se abre a TODA la fuerza de
        # ventas (P4 sigue siendo de mayoristas y P5 del autorizador).
        return ['high', 'medium', 'minimum']

    @api.model
    def _get_user_threshold_level(self, user=None):
        """
        Devuelve el nivel ('high', 'medium', 'minimum', 'level_4', 'level_5') por
        debajo del cual el usuario requiere solicitar autorización.

        - Vendedor regular: minimum (el Precio 3 es libre; DEBAJO de él
          requiere autorización — política 31 ago 2026).
        - Vendedor mayorista: level_4 (debajo del Precio 4 requiere autorización).
        - Autorizador: level_5 (debajo del Precio 5 requiere autorización).
        """
        role = self._get_user_price_role(user=user)
        if role == 'authorizer':
            return 'level_5'
        if role == 'mayorista':
            return 'level_4'
        return 'minimum'

    @api.model
    def _get_price_level_value(self, tmpl, level, currency_code, company=None):
        """Lee del template el valor del nivel pedido en la moneda solicitada.

        La escalera es company_dependent: con `company` (la del documento:
        orden, apartado, autorización) se lee la de ESA compañía; sin ella,
        la de la compañía activa del usuario (defaults/UI)."""
        if not tmpl:
            return 0.0

        if company:
            tmpl = tmpl.with_company(company)

        if currency_code == 'MXN':
            mapping = {
                'high': tmpl.x_price_mxn_1,
                'medium': tmpl.x_price_mxn_2,
                'minimum': tmpl.x_price_mxn_3,
                'level_4': tmpl.x_price_mxn_4,
                'level_5': tmpl.x_price_mxn_5,
            }
        else:
            mapping = {
                'high': tmpl.x_price_usd_1,
                'medium': tmpl.x_price_usd_2,
                'minimum': tmpl.x_price_usd_3,
                'level_4': tmpl.x_price_usd_4,
                'level_5': tmpl.x_price_usd_5,
            }
        return mapping.get(level, 0.0) or 0.0

    @api.model
    def get_custom_prices(self, product_id, currency_code):
        product_variant = self.env['product.product'].browse(int(product_id))
        product = product_variant.product_tmpl_id if product_variant.exists() else self.browse(int(product_id))

        visible_levels = self._get_user_visible_price_levels()
        threshold_level = self._get_user_threshold_level()

        # Mismo nombre que en el tooltip del Inventario Visual, en las
        # autorizaciones y en la ficha del producto: "Precio 1"…"Precio 5".
        # (Antes traían doble espacio y paréntesis: 'Precio  (1)'.)
        labels = {
            'high': 'Precio 1',
            'medium': 'Precio 2',
            'minimum': 'Precio 3',
            'level_4': 'Precio 4',
            'level_5': 'Precio 5',
        }

        prices = []
        for level in visible_levels:
            prices.append({
                'label': labels.get(level, level),
                'value': self._get_price_level_value(product, level, currency_code),
                'level': level,
                'is_threshold': level == threshold_level,
            })

        return prices

    @api.model
    def get_price_tooltip_data(self, product_id):
        """Precios de referencia por ROL (lo consume el Inventario Visual):
        vendedor regular ve niveles 1-2; mayorista, 1-4; autorizador y visor
        del Dashboard, 1-5."""
        product = self.env['product.product'].browse(product_id)

        if not product.exists():
            return {}

        tmpl = product.product_tmpl_id
        role = self._get_user_price_role()

        # Las etiquetas van NUMERADAS ('Precio 1'…'Precio 5'), que es como
        # se le nombra a la escalera en toda la casa. Antes decían
        # 'Alto'/'Medio'/'Mínimo' y el vendedor tenía que traducir: en el
        # carrito, en las autorizaciones y en la orden se habla de Precio 1
        # y Precio 2. El color del punto sigue marcando qué tan abajo va
        # cada nivel (verde arriba → rojo en el piso).
        levels = [
            {'label': 'Precio 1', 'dot': '#28a745',
             'usd': tmpl.x_price_usd_1, 'mxn': tmpl.x_price_mxn_1},
            {'label': 'Precio 2', 'dot': '#ffc107',
             'usd': tmpl.x_price_usd_2, 'mxn': tmpl.x_price_mxn_2},
        ]
        # Precio 3: abierto a toda la fuerza de ventas (política 31 ago 2026).
        levels += [
            {'label': 'Precio 3', 'dot': '#fd7e14',
             'usd': tmpl.x_price_usd_3, 'mxn': tmpl.x_price_mxn_3},
        ]
        if role in ('mayorista', 'authorizer'):
            levels += [
                {'label': 'Precio 4', 'dot': '#6f42c1',
                 'usd': tmpl.x_price_usd_4, 'mxn': tmpl.x_price_mxn_4},
            ]
        # El Precio 5 (mínimo absoluto) es exclusivo del autorizador y del
        # visor del Dashboard: el mayorista NO lo ve.
        if role == 'authorizer':
            levels += [
                {'label': 'Precio 5', 'dot': '#dc3545',
                 'usd': tmpl.x_price_usd_5, 'mxn': tmpl.x_price_mxn_5},
            ]

        return {
            'levels': levels,
            # Compatibilidad con consumidores viejos del tooltip
            'usd_high': tmpl.x_price_usd_1,
            'usd_medium': tmpl.x_price_usd_2,
            'mxn_high': tmpl.x_price_mxn_1,
            'mxn_medium': tmpl.x_price_mxn_2,
        }

    @api.model
    def check_price_authorization_needed(self, product_prices, currency_code, company=None):
        """
        Valida si una operación requiere autorización de precio.

        Regla por rol:
        - Vendedor regular: autorización si el precio queda debajo del Precio 3
          (política 31 ago 2026: el Precio 3 es libre para toda la fuerza de ventas).
        - Vendedor mayorista: autorización si el precio queda debajo del Precio 4.
        - Autorizador/Administrador: autorización si el precio queda debajo del Precio 5.
        - Usuarios sin rol comercial explícito no disparan autorización desde este helper.

        `company`: compañía del documento para leer la escalera
        (company_dependent); sin ella, la activa del usuario.
        """
        needs_auth = []
        if company:
            self = self.with_company(company)
        role = self._get_user_price_role()
        is_authorizer = role == 'authorizer'

        if role == 'none':
            return {
                'needs_authorization': False,
                'products': [],
                'is_authorizer': is_authorizer,
                'role': role,
            }

        threshold_level = self._get_user_threshold_level()
        threshold_label_map = {
            'medium': 'Precio 2',
            'minimum': 'Precio 3',
            'level_4': 'Precio 4',
            'level_5': 'Precio 5',
        }

        for product_id_str, requested_price in (product_prices or {}).items():
            product_variant = self.env['product.product'].browse(int(product_id_str))
            product = product_variant.product_tmpl_id if product_variant.exists() else self.browse(int(product_id_str))

            if not product.exists():
                continue

            try:
                requested_price = float(requested_price or 0.0)
            except Exception:
                requested_price = 0.0

            medium = self._get_price_level_value(product, 'medium', currency_code)
            minimum = self._get_price_level_value(product, 'minimum', currency_code)
            level_4 = self._get_price_level_value(product, 'level_4', currency_code)
            level_5 = self._get_price_level_value(product, 'level_5', currency_code)
            threshold = self._get_price_level_value(product, threshold_level, currency_code)

            if threshold > 0 and requested_price < (threshold - 0.01):
                needs_auth.append({
                    'product_id': int(product_id_str),
                    'product_name': product_variant.display_name if product_variant.exists() else product.display_name,
                    'requested_price': requested_price,
                    'medium_price': medium,
                    'minimum_price': minimum,
                    'level_4_price': level_4,
                    'level_5_price': level_5,
                    'threshold_price': threshold,
                    'threshold_label': threshold_label_map.get(threshold_level, threshold_level),
                })

        return {
            'needs_authorization': len(needs_auth) > 0,
            'products': needs_auth,
            'is_authorizer': is_authorizer,
            'role': role,
        }


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _name_search(self, name='', domain=None, operator='ilike', limit=None, order=None):
        """En el selector de producto del apartado (hold), los servicios
        (p. ej. anticipos) NO se listan por defecto al abrir el desplegable,
        pero SÍ aparecen cuando el usuario escribe algo para buscarlos.

        Se activa solo cuando el campo pasa el contexto 'hold_hide_services_default'
        y la búsqueda está vacía (desplegable recién abierto).
        """
        if self.env.context.get('hold_hide_services_default') and not name:
            domain = list(domain or []) + [('type', '!=', 'service')]
        return super()._name_search(
            name=name, domain=domain, operator=operator,
            limit=limit, order=order,
        )

    def write(self, vals):
        res = super(ProductProduct, self).write(vals)

        if 'standard_price' in vals:
            for product in self:
                product.product_tmpl_id._compute_costo_all_in()
                product.product_tmpl_id._calculate_escalera_precios()

        return res