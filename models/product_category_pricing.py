# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ProductCategoryPricing(models.Model):
    _name = 'product.category.pricing'
    _description = 'Configuración de Utilidad por Categoría'
    _order = 'categ_id'
    _rec_name = 'categ_id'

    categ_id = fields.Many2one(
        'product.category', string='Categoría',
        required=True, ondelete='cascade',
    )

    # === MODO DE PRECIO ===
    pricing_mode = fields.Selection([
        ('calculated', 'Calculado (Costo + Utilidad)'),
        ('fixed', 'Precio Fijo'),
    ], string='Modo de Precio', default='calculated', required=True,
       help="Calculado: Precio = Costo / (1 - %Utilidad). "
            "Fijo: Se parte de un precio fijo y se aplican las utilidades como niveles de descuento.")

    x_fixed_price = fields.Float(
        string='Precio Fijo Base',
        digits='Product Price',
        help="Precio base fijo desde el cual se calculan los niveles medio y mínimo.",
    )

    # === UTILIDADES DIRECTAS ===
    x_utilidad = fields.Float(string='% Utilidad Alta', default=40.0,
                              help="Margen de utilidad para el Precio Alto (Nivel 1).")
    x_utilidad_media = fields.Float(string='% Utilidad Media', default=35.0,
                                    help="Margen de utilidad para el Precio Medio (Nivel 2).")
    x_utilidad_minima = fields.Float(string='% Utilidad Mínima', default=30.0,
                                     help="Margen de utilidad para el Precio Mínimo (Nivel 3).")

    # === ARANCEL ===
    x_arancel_pct = fields.Float(string='Arancel (%)', default=0.0,
                                 help="Porcentaje de arancel a aplicar sobre el costo bruto de compra.")

    product_count = fields.Integer(
        string='Productos', compute='_compute_product_count',
    )

    _sql_constraints = [
        ('categ_unique', 'unique(categ_id)', 'Ya existe una configuración para esta categoría.'),
    ]

    @api.depends('categ_id')
    def _compute_product_count(self):
        for rec in self:
            rec.product_count = self.env['product.template'].search_count([
                ('categ_id', '=', rec.categ_id.id),
            ])

    def action_apply_to_products(self):
        """Aplica utilidades, modo de precio, precio fijo y arancel a todos los productos de la categoría"""
        self.ensure_one()
        products = self.env['product.template'].search([
            ('categ_id', '=', self.categ_id.id),
        ])
        if not products:
            raise UserError(f'No hay productos en la categoría "{self.categ_id.complete_name}".')

        vals = {
            'x_utilidad': self.x_utilidad,
            'x_utilidad_media': self.x_utilidad_media,
            'x_utilidad_minima': self.x_utilidad_minima,
            'x_arancel_pct': self.x_arancel_pct,
            'x_pricing_mode': self.pricing_mode,
        }
        if self.pricing_mode == 'fixed':
            vals['x_fixed_price'] = self.x_fixed_price

        products.write(vals)

        # Forzar recálculo
        products._compute_costo_all_in()
        products._calculate_escalera_precios()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Utilidades Aplicadas',
                'message': f'{len(products)} productos actualizados en "{self.categ_id.complete_name}".',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_apply_all(self):
        """Botón para aplicar TODAS las configuraciones seleccionadas"""
        for rec in self:
            rec.action_apply_to_products()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Aplicación Masiva',
                'message': f'{len(self)} categorías procesadas.',
                'type': 'success',
                'sticky': False,
            },
        }