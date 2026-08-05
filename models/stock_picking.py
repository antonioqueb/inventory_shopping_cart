# ./models/stock_picking.py
# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError
from collections import defaultdict

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Reservas comerciales (venta/entrega) desplazadas temporalmente por este
    # traslado de bin del carrito/escáner. Al validar el traslado se vuelven a
    # anclar en la ubicación destino; si el traslado se cancela, se restauran
    # en la ubicación original.
    som_displaced_reservations_json = fields.Text(
        string='Reservas desplazadas (JSON)', copy=False,
    )

    @api.model
    def _som_displace_strong_reservations(self, lot_ids):
        """Desancla temporalmente las reservas comerciales de estos lotes.

        Regla de negocio: un movimiento de BIN siempre está permitido, aunque
        el lote esté reservado por una venta/entrega. Como la reserva nativa
        de Odoo vive anclada a la ubicación, aquí se desancla (unlink de las
        move lines reservadas) y se devuelve la lista de entradas para
        volver a anclarla después:
        - al VALIDAR el traslado de bin → en la ubicación destino;
        - al CANCELAR el traslado → en la ubicación original.
        """
        entries = []
        lot_ids = [lid for lid in set(lot_ids or []) if lid]
        if not lot_ids:
            return entries

        strong_lines = self.env['stock.move.line'].sudo().search([
            ('lot_id', 'in', lot_ids),
            ('state', 'in', ('assigned', 'partially_available')),
            ('quantity', '>', 0),
            ('picking_id', '!=', False),
            ('picking_id.state', 'not in', ('done', 'cancel')),
        ]).filtered(lambda ml: not (
            ml.picking_id.picking_type_code == 'internal'
            and (ml.picking_id.origin or '').startswith('Carrito - ')
        ))

        for ml in strong_lines:
            entries.append({
                'move_id': ml.move_id.id,
                'picking_id': ml.picking_id.id,
                'picking_name': ml.picking_id.name or '',
                'product_id': ml.product_id.id,
                'lot_id': ml.lot_id.id,
                'lot_name': ml.lot_id.name or '',
                'qty': ml.quantity,
                'uom_id': ml.product_uom_id.id,
                'location_id': ml.location_id.id,
                'location_dest_id': ml.location_dest_id.id,
                'company_id': ml.company_id.id,
            })

        if strong_lines:
            # skip_stone_sync_so: que el sync picking→línea de venta no
            # interprete el desanclaje temporal como "quitar el lote de la SO".
            strong_lines.with_context(
                skip_stone_sync_so=True,
                skip_hold_validation=True,
                skip_duplicate_lot_validation=True,
            ).unlink()

        return entries

    @api.model
    def _som_reanchor_displaced_reservations(self, entries, location_id=None):
        """Vuelve a anclar reservas desplazadas por un movimiento de bin.

        location_id: ubicación donde re-reservar (destino del traslado). Si es
        None, cada entrada se restaura en su ubicación original.
        Devuelve (restauradas, fallidas). Las fallidas no revientan el flujo:
        se reporta en el chatter del documento afectado para reasignar a mano.
        """
        MoveLine = self.env['stock.move.line'].sudo().with_context(
            skip_stone_sync_so=True,
            skip_hold_validation=True,
            skip_duplicate_lot_validation=True,
        )
        Move = self.env['stock.move'].sudo()
        restored, failed = [], []

        for entry in entries or []:
            move = Move.browse(entry.get('move_id')).exists()
            if not move or move.state in ('done', 'cancel'):
                failed.append(entry)
                continue
            try:
                MoveLine.create({
                    'move_id': move.id,
                    'picking_id': entry.get('picking_id'),
                    'product_id': entry.get('product_id'),
                    'lot_id': entry.get('lot_id'),
                    'quantity': entry.get('qty'),
                    'product_uom_id': entry.get('uom_id'),
                    'location_id': location_id or entry.get('location_id'),
                    'location_dest_id': entry.get('location_dest_id'),
                    'company_id': entry.get('company_id'),
                })
                restored.append(entry)
            except Exception:
                _logger.exception(
                    '[BIN MOVE] No se pudo re-anclar la reserva del lote %s '
                    'para %s tras el movimiento de bin.',
                    entry.get('lot_name'), entry.get('picking_name'),
                )
                failed.append(entry)
                target = self.env['stock.picking'].sudo().browse(
                    entry.get('picking_id')).exists()
                if target:
                    target.message_post(body=(
                        'El lote %s se movió de bin y no se pudo re-reservar '
                        'automáticamente. Usa "Comprobar disponibilidad" para '
                        'reasignarlo.' % (entry.get('lot_name') or '')
                    ))

        return restored, failed

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
                # (action_cancel restaura las reservas desplazadas en su
                # ubicación original.)
                stale_picking.action_cancel()
            else:
                # Traía otros lotes: solo se liberan los conflictivos y se
                # ajusta la demanda para no dejar faltantes fantasma.
                doomed_lot_ids = set(doomed.mapped('lot_id').ids)
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

                # Restaurar en su ubicación original las reservas
                # comerciales desplazadas de los lotes liberados; las de
                # los lotes que siguen en el traslado se conservan.
                if stale_picking.som_displaced_reservations_json:
                    try:
                        entries = json.loads(
                            stale_picking.som_displaced_reservations_json)
                    except (TypeError, ValueError):
                        entries = []
                    to_restore = [
                        e for e in entries
                        if e.get('lot_id') in doomed_lot_ids
                    ]
                    to_keep = [
                        e for e in entries
                        if e.get('lot_id') not in doomed_lot_ids
                    ]
                    if to_restore:
                        self._som_reanchor_displaced_reservations(to_restore)
                    stale_picking.som_displaced_reservations_json = (
                        json.dumps(to_keep) if to_keep else False)
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

        # MOVIMIENTO DE BIN SIEMPRE PERMITIDO: si algún lote está reservado
        # por una venta/entrega, la reserva se desancla aquí (para que la
        # creación del traslado no choque con la reserva nativa) y se vuelve
        # a anclar en el bin destino al validar, o en el original si el
        # traslado se cancela.
        displaced_entries = self._som_displace_strong_reservations(
            list(superseded_lot_ids))
        displaced_by_lot = defaultdict(list)
        for entry in displaced_entries:
            displaced_by_lot[entry['lot_id']].append(entry)

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

            picking_lot_ids = {
                q.lot_id.id for q in quants_list if q.lot_id
            }
            picking_displaced = [
                entry
                for lot_id in picking_lot_ids
                for entry in displaced_by_lot.get(lot_id, [])
            ]
            if picking_displaced:
                picking.som_displaced_reservations_json = json.dumps(
                    picking_displaced)
                docs = sorted({
                    e.get('picking_name') or '' for e in picking_displaced
                })
                picking.message_post(body=(
                    'Este traslado mueve lotes reservados por: %s. La '
                    'reserva se re-anclará automáticamente en el bin '
                    'destino al validar.' % ', '.join(d for d in docs if d)
                ))

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

    def button_validate(self):
        res = super().button_validate()

        # Primera ENTREGA validada de una orden: congela su tipo de cambio
        # (la confirmación de la orden ya no congela nada).
        for picking in self:
            if (
                picking.state == 'done'
                and picking.picking_type_code == 'outgoing'
                and picking.sale_id
                and 'x_delivery_exchange_rate' in picking.sale_id._fields
            ):
                picking.sale_id.sudo()._som_freeze_delivery_rate()

        # Traslado de bin validado: re-anclar en el bin destino las reservas
        # comerciales que este traslado desplazó al crearse.
        for picking in self:
            if picking.state != 'done':
                continue
            if not picking.som_displaced_reservations_json:
                continue
            try:
                entries = json.loads(picking.som_displaced_reservations_json)
            except (TypeError, ValueError):
                entries = []
            if not entries:
                picking.som_displaced_reservations_json = False
                continue

            restored, failed = self._som_reanchor_displaced_reservations(
                entries, location_id=picking.location_dest_id.id)
            picking.som_displaced_reservations_json = False

            if restored:
                docs = sorted({
                    e.get('picking_name') or '' for e in restored
                })
                picking.message_post(body=(
                    'Reservas re-ancladas en %s para: %s.' % (
                        picking.location_dest_id.complete_name,
                        ', '.join(d for d in docs if d),
                    )
                ))

        return res

    def action_cancel(self):
        # Antes de cancelar, capturar los desplazamientos pendientes para
        # restaurar las reservas comerciales en su ubicación ORIGINAL (el
        # material nunca se movió).
        pending = {}
        for picking in self:
            if picking.som_displaced_reservations_json and picking.state not in ('done', 'cancel'):
                try:
                    pending[picking.id] = json.loads(
                        picking.som_displaced_reservations_json)
                except (TypeError, ValueError):
                    pending[picking.id] = []

        res = super().action_cancel()

        for picking in self:
            entries = pending.get(picking.id)
            if not entries:
                continue
            self._som_reanchor_displaced_reservations(entries)
            picking.som_displaced_reservations_json = False

        return res