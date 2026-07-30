# ./models/stock_picking.py
# -*- coding: utf-8 -*-
from odoo import models, api
from odoo.exceptions import UserError
from collections import defaultdict

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def _release_cart_internal_reservations(self, lot_ids, reason=None):
        """Libera traslados internos de carrito/escáner ABIERTOS que retienen
        estos lotes.

        Regla de negocio: un traslado interno creado desde el carrito o el
        escáner móvil (origin 'Carrito - %') es solo REACOMODO DE UBICACIÓN,
        una reserva DÉBIL. Nunca debe competir con una venta, apartado,
        entrega, orden de taller ni con un traslado nuevo del propio carrito.
        Cualquier flujo fuerte llama aquí antes de validar disponibilidad y
        el traslado viejo cede: se cancela (si todos sus lotes se necesitan)
        o se le quitan solo los lotes en conflicto ajustando la demanda.

        Devuelve los pickings tocados.
        """
        lot_ids = [lid for lid in set(lot_ids or []) if lid]
        touched = self.env['stock.picking'].sudo().browse()
        if not lot_ids:
            return touched

        stale_lines = self.env['stock.move.line'].sudo().search([
            ('lot_id', 'in', lot_ids),
            ('state', 'not in', ('done', 'cancel')),
            ('picking_id.picking_type_code', '=', 'internal'),
            ('picking_id.origin', '=like', 'Carrito - %'),
            ('picking_id.state', 'not in', ('done', 'cancel')),
        ])
        default_reason = (
            'Liberado automáticamente: sus lotes se necesitan en otra '
            'operación (venta, apartado, taller o traslado nuevo). Mover '
            'material de ubicación no compromete el lote.'
        )
        for stale_picking in stale_lines.mapped('picking_id'):
            pending = stale_picking.move_line_ids.filtered(
                lambda ml: ml.state not in ('done', 'cancel'))
            doomed = pending.filtered(lambda ml: ml.lot_id.id in lot_ids)
            if not doomed:
                continue
            if doomed == pending:
                # Todo el traslado viejo era de estos lotes: se cancela.
                stale_picking.action_cancel()
            else:
                # Traía otros lotes: solo se liberan los conflictivos y se
                # ajusta la demanda para no dejar faltantes fantasma.
                for move in doomed.mapped('move_id'):
                    move_doomed = doomed.filtered(
                        lambda ml: ml.move_id == move)
                    released = sum(move_doomed.mapped('quantity'))
                    move_doomed.unlink()
                    remaining = max(
                        (move.product_uom_qty or 0.0) - released, 0.0)
                    if remaining <= 0:
                        move._action_cancel()
                    else:
                        move.product_uom_qty = remaining
            stale_picking.message_post(body=reason or default_reason)
            touched |= stale_picking
        return touched

    @api.model
    def create_transfer_from_shopping_cart(self, selected_lots=None, location_dest_id=None, notes=None, partner_id=None):
        """
        Crea traslados internos desde el carrito de compras
        Agrupa los lotes por ubicación origen y crea un picking por cada ubicación
        """
        if not self.env.user.has_group('stock.group_stock_user'):
            raise UserError("No tiene permisos para crear traslados internos")
        
        if not selected_lots or not location_dest_id:
            raise UserError("Faltan parámetros: selected_lots o location_dest_id")
        
        location_dest = self.env['stock.location'].browse(location_dest_id)
        if not location_dest.exists():
            raise UserError("La ubicación destino no existe")
        
        if location_dest.usage != 'internal':
            raise UserError("La ubicación destino debe ser de tipo 'Ubicación Interna'")
        
        quants = self.env['stock.quant'].browse(selected_lots)
        location_groups = defaultdict(list)
        
        for quant in quants:
            if not quant.exists():
                continue
            
            if quant.quantity <= 0:
                raise UserError(f"El lote {quant.lot_id.name} no tiene cantidad disponible")
            
            location_groups[quant.location_id.id].append(quant)
        
        if not location_groups:
            raise UserError("No hay lotes válidos para trasladar")

        # SUPERSESIÓN: un traslado de carrito PENDIENTE que retiene alguno de
        # estos mismos lotes es un residuo (el usuario está re-ordenando el
        # movimiento desde el carrito/escáner). Se libera solo; sin esto, el
        # guardia de duplicados bloqueaba el traslado nuevo con "lote
        # comprometido en otra operación activa" (SOM/INT abierto).
        superseded_lot_ids = {
            quant.lot_id.id
            for group in location_groups.values()
            for quant in group
            if quant.lot_id
        }
        self._release_cart_internal_reservations(
            list(superseded_lot_ids),
            reason='Liberado automáticamente: sus lotes se volvieron a '
                   'mover desde el carrito/escáner en un traslado nuevo.',
        )

        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '!=', False)
        ], limit=1)
        
        if not picking_type:
            raise UserError("No se encontró un tipo de operación para traslados internos")
        
        created_pickings = []
        current_user = self.env.user
        
        for location_origin_id, quants_list in location_groups.items():
            location_origin = self.env['stock.location'].browse(location_origin_id)
            
            product_groups = defaultdict(list)
            for quant in quants_list:
                product_groups[quant.product_id.id].append(quant)
            
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
            
            for product_id, product_quants in product_groups.items():
                product = self.env['product.product'].browse(product_id)
                total_quantity = sum(q.quantity for q in product_quants)
                
                move_vals = {
                    'product_id': product_id,
                    'product_uom_qty': total_quantity,
                    'product_uom': product.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': location_origin_id,
                    'location_dest_id': location_dest_id,
                    'company_id': picking.company_id.id,
                }
                
                move = self.env['stock.move'].create(move_vals)
                
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
            
            picking.action_confirm()
            picking.action_assign()
            
            created_pickings.append({
                'id': picking.id,
                'name': picking.name,
                'location_origin': location_origin.complete_name,
                'moves_count': len(picking.move_ids)
            })
        
        self.env['shopping.cart'].clear_cart()
        
        return {
            'success': True,
            'pickings': created_pickings,
            'total_pickings': len(created_pickings)
        }