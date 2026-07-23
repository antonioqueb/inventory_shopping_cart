# -*- coding: utf-8 -*-
"""Relación Cliente → Proyectos → Ventas.

Un cliente tiene muchos proyectos; una orden de venta pertenece a UN
proyecto. Aquí viven las métricas que alimentan el análisis: cuánto se ha
vendido por proyecto, cuántas cotizaciones/órdenes tiene y de qué cliente es.
"""
from odoo import models, fields, api


class ProjectProject(models.Model):
    _inherit = 'project.project'

    som_sale_order_ids = fields.One2many(
        'sale.order', 'x_project_id',
        string='Ventas del proyecto',
    )
    som_sale_count = fields.Integer(
        string='Órdenes de venta', compute='_compute_som_sale_metrics',
    )
    som_quotation_count = fields.Integer(
        string='Cotizaciones', compute='_compute_som_sale_metrics',
    )
    som_amount_sold = fields.Monetary(
        string='Monto vendido', compute='_compute_som_sale_metrics',
        currency_field='som_currency_id',
        help='Suma de las órdenes CONFIRMADAS del proyecto.',
    )
    som_amount_quoted = fields.Monetary(
        string='Monto cotizado', compute='_compute_som_sale_metrics',
        currency_field='som_currency_id',
        help='Suma de las cotizaciones (borrador/enviada) del proyecto.',
    )
    som_currency_id = fields.Many2one(
        'res.currency', compute='_compute_som_sale_metrics',
    )

    @api.depends('som_sale_order_ids.state', 'som_sale_order_ids.amount_total')
    def _compute_som_sale_metrics(self):
        for project in self:
            orders = project.som_sale_order_ids
            confirmed = orders.filtered(lambda o: o.state in ('sale', 'done'))
            quotes = orders.filtered(lambda o: o.state in ('draft', 'sent'))
            project.som_sale_count = len(confirmed)
            project.som_quotation_count = len(quotes)
            project.som_amount_sold = sum(confirmed.mapped('amount_total'))
            project.som_amount_quoted = sum(quotes.mapped('amount_total'))
            project.som_currency_id = (
                orders[:1].currency_id or self.env.company.currency_id
            )

    def action_som_view_sales(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Ventas — %s' % self.name,
            'res_model': 'sale.order',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('x_project_id', '=', self.id),
                       ('state', 'in', ('sale', 'done'))],
            'context': {'default_x_project_id': self.id,
                        'default_partner_id': self.partner_id.id},
        }

    def action_som_view_quotations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cotizaciones — %s' % self.name,
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('x_project_id', '=', self.id),
                       ('state', 'in', ('draft', 'sent'))],
            'context': {'default_x_project_id': self.id,
                        'default_partner_id': self.partner_id.id},
        }
