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
    x_utilidad = fields.Float(string='% Utilidad Base', default=40.0)
    x_discount_medium = fields.Float(string='% Descuento Medio', default=5.0)
    x_discount_minimum = fields.Float(string='% Descuento Mínimo', default=5.0)

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
        """Aplica los 3 niveles de utilidad a todos los productos de la categoría"""
        self.ensure_one()
        products = self.env['product.template'].search([
            ('categ_id', '=', self.categ_id.id),
        ])
        if not products:
            raise UserError(f'No hay productos en la categoría "{self.categ_id.complete_name}".')

        products.write({
            'x_utilidad': self.x_utilidad,
            'x_discount_medium': self.x_discount_medium,
            'x_discount_minimum': self.x_discount_minimum,
        })
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