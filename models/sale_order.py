# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    x_selected_lots = fields.Many2many('stock.quant', string='Lotes Seleccionados')

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    # Nota: Asegúrate de que estos campos existan en la base de datos
    # (generalmente definidos en stock_lot_dimensions si este es inventory_shopping_cart)
    # Si este es el único módulo donde se definen, descomenta las siguientes líneas:
    # x_project_id = fields.Many2one('project.project', string='Proyecto')
    # x_architect_id = fields.Many2one('res.partner', string='Arquitecto')
    
    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, notes=None, pricelist_id=None, apply_tax=True, project_id=None, architect_id=None):
        """
        Crea una orden de venta desde el carrito de compras.
        Actualizado para recibir Proyecto y Arquitecto.
        """
        if not partner_id or not products:
            raise UserError("Faltan parámetros: partner_id o products")
        
        if not pricelist_id:
            raise UserError("Debe especificar una lista de precios")
        
        # 1. Validar que los lotes no estén apartados por OTRO cliente
        for product in products:
            # Verificación de seguridad por si el producto no trae lotes
            if 'selected_lots' in product and product['selected_lots']:
                for quant_id in product['selected_lots']:
                    quant = self.env['stock.quant'].browse(quant_id)
                    if quant.x_tiene_hold:
                        hold_partner = quant.x_hold_activo_id.partner_id
                        if hold_partner.id != partner_id:
                            raise UserError(f"El lote {quant.lot_id.name} está apartado para {hold_partner.name}")
        
        # 2. Crear la Orden de Venta (Incluyendo Proyecto y Arquitecto)
        vals_create = {
            'partner_id': partner_id,
            'note': notes or '',
            'pricelist_id': pricelist_id,
            'x_project_id': project_id,      # <--- AGREGADO
            'x_architect_id': architect_id,  # <--- AGREGADO
        }
        
        sale_order = self.env['sale.order'].create(vals_create)
        
        # 3. Crear Líneas de Orden
        for product in products:
            product_rec = self.env['product.product'].browse(product['product_id'])
            
            if apply_tax and product_rec.taxes_id:
                tax_ids = [(6, 0, product_rec.taxes_id.ids)]
            else:
                tax_ids = [(5, 0, 0)]
            
            line_vals = {
                'order_id': sale_order.id,
                'product_id': product['product_id'],
                'product_uom_qty': product['quantity'],
                'price_unit': product['price_unit'],
                'tax_id': tax_ids,
            }
            
            # Asignar lotes seleccionados si existen
            if 'selected_lots' in product and product['selected_lots']:
                line_vals['x_selected_lots'] = [(6, 0, product['selected_lots'])]
                
            self.env['sale.order.line'].create(line_vals)
        
        # 4. Confirmar Orden
        sale_order.action_confirm()
        
        # 5. Asignación forzosa de los lotes específicos al Picking
        for line in sale_order.order_line:
            if line.x_selected_lots:
                picking = line.move_ids.mapped('picking_id')
                if picking:
                    self._assign_specific_lots(picking, line.product_id, line.x_selected_lots)
        
        # 6. Limpiar carrito después de crear orden
        self.env['shopping.cart'].clear_cart()
        
        return {
            'success': True,
            'order_id': sale_order.id,
            'order_name': sale_order.name
        }
    
    def _assign_specific_lots(self, picking, product, quants):
        """
        Reemplaza la asignación automática de Odoo con los lotes específicos seleccionados por el usuario.
        """
        for move in picking.move_ids.filtered(lambda m: m.product_id == product):
            # Desvincular líneas reservadas automáticamente por Odoo
            move.move_line_ids.unlink()
            
            move_line_model = self.env['stock.move.line'].with_context(skip_hold_validation=True)
            
            for quant in quants:
                move_line_model.create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    'lot_id': quant.lot_id.id,
                    'location_id': quant.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'quantity': quant.quantity, # Asignar la cantidad completa del quant
                    'product_uom_id': move.product_uom.id,
                })