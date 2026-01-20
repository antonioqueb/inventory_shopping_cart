# ./models/stock_picking.py
# -*- coding: utf-8 -*-
from odoo import models, api
from odoo.exceptions import UserError
from collections import defaultdict

class StockPicking(models.Model):
    _inherit = 'stock.picking'
    
    @api.model
    def create_transfer_from_shopping_cart(self, selected_lots=None, location_dest_id=None, notes=None, partner_id=None):
        """
        Crea traslados internos desde el carrito de compras
        Agrupa los lotes por ubicación origen y crea un picking por cada ubicación
        """
        # ✅ VALIDACIÓN DE PERMISOS
        if not self.env.user.has_group('stock.group_stock_user'):
            raise UserError("No tiene permisos para crear traslados internos")
        
        if not selected_lots or not location_dest_id:
            raise UserError("Faltan parámetros: selected_lots o location_dest_id")
        
        # Verificar que la ubicación destino existe y es interna
        location_dest = self.env['stock.location'].browse(location_dest_id)
        if not location_dest.exists():
            raise UserError("La ubicación destino no existe")
        
        if location_dest.usage != 'internal':
            raise UserError("La ubicación destino debe ser de tipo 'Ubicación Interna'")
        
        # Obtener quants y agrupar por ubicación origen
        quants = self.env['stock.quant'].browse(selected_lots)
        location_groups = defaultdict(list)
        
        for quant in quants:
            if not quant.exists():
                continue
            
            # Verificar disponibilidad
            if quant.quantity <= 0:
                raise UserError(f"El lote {quant.lot_id.name} no tiene cantidad disponible")
            
            location_groups[quant.location_id.id].append(quant)
        
        if not location_groups:
            raise UserError("No hay lotes válidos para trasladar")
        
        # Buscar el tipo de operación de traslado interno
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '!=', False)
        ], limit=1)
        
        if not picking_type:
            raise UserError("No se encontró un tipo de operación para traslados internos")
        
        created_pickings = []
        current_user = self.env.user
        
        # Crear un picking por cada ubicación origen
        for location_origin_id, quants_list in location_groups.items():
            location_origin = self.env['stock.location'].browse(location_origin_id)
            
            # Agrupar quants por producto
            product_groups = defaultdict(list)
            for quant in quants_list:
                product_groups[quant.product_id.id].append(quant)
            
            # ✅ CREAR EL PICKING SIN PARTNER_ID
            picking_vals = {
                'picking_type_id': picking_type.id,
                'location_id': location_origin_id,
                'location_dest_id': location_dest_id,
                'origin': f'Carrito - {current_user.name}',
                'note': notes or '',
                'user_id': current_user.id,
                'move_type': 'direct',
            }
            
            picking = self.create(picking_vals)
            
            # Crear movimientos para cada producto
            for product_id, product_quants in product_groups.items():
                product = self.env['product.product'].browse(product_id)
                total_quantity = sum(q.quantity for q in product_quants)
                
                # ✅ CREAR EL stock.move SIN EL CAMPO 'name' (se genera automáticamente)
                move_vals = {
                    'product_id': product_id,
                    'product_uom_qty': total_quantity,
                    'product_uom_id': product.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': location_origin_id,
                    'location_dest_id': location_dest_id,
                    'company_id': picking.company_id.id,
                }
                
                move = self.env['stock.move'].create(move_vals)
                
                # Crear stock.move.line para cada lote específico
                for quant in product_quants:
                    move_line_vals = {
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': product_id,
                        'lot_id': quant.lot_id.id,
                        'location_id': location_origin_id,
                        'location_dest_id': location_dest_id,
                        'quantity': quant.quantity,
                        'product_uom_id': product.uom_id.id,
                        'company_id': picking.company_id.id,
                    }
                    self.env['stock.move.line'].create(move_line_vals)
            
            # Confirmar el picking
            picking.action_confirm()
            
            # Asignar cantidades
            picking.action_assign()
            
            created_pickings.append({
                'id': picking.id,
                'name': picking.name,
                'location_origin': location_origin.complete_name,
                'moves_count': len(picking.move_ids)
            })
        
        # Limpiar carrito
        self.env['shopping.cart'].clear_cart()
        
        return {
            'success': True,
            'pickings': created_pickings,
            'total_pickings': len(created_pickings)
        }