# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import models, fields, api
from odoo.addons.inventory_shopping_cart.models.som_date_format import som_format_date
from odoo.models import Constraint

_logger = logging.getLogger(__name__)

class ShoppingCart(models.Model):
    _name = 'shopping.cart'
    _description = 'Carrito de Compras Persistente'

    # Regla de negocio: el carrito retiene material MÁXIMO 24 horas sin
    # movimiento (movimiento = cualquier write, p. ej. actualizar cantidad).
    # Pasado el plazo, el material se libera solo (cron + GC oportunista).
    CART_TTL_HOURS = 24
    
    user_id = fields.Many2one('res.users', string='Usuario', required=True, default=lambda self: self.env.user, index=True)
    quant_id = fields.Many2one('stock.quant', string='Quant', required=True, ondelete='cascade')
    lot_id = fields.Integer(string='Lote ID', required=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    quantity = fields.Float(string='Cantidad', required=True)
    location_name = fields.Char(string='Ubicación')
    added_at = fields.Datetime(string='Agregado', default=fields.Datetime.now)
    # Multiempresa: la entrada de carrito pertenece a la compañía del
    # material (quant), no a la del usuario que lo agregó.
    company_id = fields.Many2one(
        'res.company', string='Compañía', related='quant_id.company_id',
        store=True, readonly=True, index=True)
    
    _unique_user_quant = Constraint(
        'unique(user_id, quant_id)',
        'Este lote ya está en tu carrito'
    )
    
    @api.model
    def _gc_expired(self):
        """Elimina entradas de carrito sin movimiento en CART_TTL_HOURS.
        write_date es la última actividad (crear/actualizar cantidad)."""
        limit = fields.Datetime.now() - timedelta(hours=self.CART_TTL_HOURS)
        expired = self.sudo().search([('write_date', '<', limit)])
        if expired:
            _logger.info(
                '[CART GC] Liberando %s lote(s) de carritos vencidos (24h '
                'sin movimiento): %s',
                len(expired),
                ', '.join('%s/%s' % (e.user_id.login, e.quant_id.lot_id.name or e.quant_id.id)
                          for e in expired[:20]),
            )
            expired.unlink()
        return True

    def _som_hours_left(self):
        self.ensure_one()
        elapsed = (fields.Datetime.now() - (self.write_date or self.added_at
                                            or fields.Datetime.now()))
        left = self.CART_TTL_HOURS - (elapsed.total_seconds() / 3600.0)
        return max(round(left, 1), 0.0)

    @api.model
    def _som_active_entries_for_lots(self, lot_ids, exclude_user_id=None):
        """Entradas de carrito VIVAS (post-GC) de otros usuarios para los
        lotes dados. El carrito bloquea por LOTE, no solo por quant."""
        self._gc_expired()
        domain = [('lot_id', 'in', [int(l) for l in lot_ids if l])]
        if exclude_user_id:
            domain.append(('user_id', '!=', int(exclude_user_id)))
        return self.sudo().search(domain)

    @api.model
    def get_cart_items(self):
        """Obtener items del carrito del usuario actual"""
        self._gc_expired()
        items = self.search([('user_id', '=', self.env.user.id)])
        result = []
        for item in items:
            # Usar 'stock.lot'
            lot = self.env['stock.lot'].browse(item.lot_id)
            if not lot.exists():
                continue
                
            hold_info = ''
            seller_name = ''
            
            # Verificación segura de campos que dependen de otros módulos
            tiene_hold = False
            if hasattr(item.quant_id, 'x_tiene_hold'):
                tiene_hold = item.quant_id.x_tiene_hold
                
                if tiene_hold and hasattr(item.quant_id, 'x_hold_activo_id') and item.quant_id.x_hold_activo_id:
                    hold = item.quant_id.x_hold_activo_id
                    if hasattr(item.quant_id, 'x_hold_para'):
                        hold_info = item.quant_id.x_hold_para
                    if hold.user_id:
                        seller_name = hold.user_id.name
            
            # Obtener el tipo (Placa, Formato, Pieza)
            product_type = 'placa' # Default
            if hasattr(lot, 'x_tipo') and lot.x_tipo:
                product_type = lot.x_tipo

            result.append({
                'id': item.quant_id.id,
                'lot_id': lot.id,
                'lot_name': lot.name,
                'product_id': item.product_id.id,
                'product_name': item.product_id.display_name,
                'quantity': item.quantity,
                'location_name': item.location_name,
                'tiene_hold': tiene_hold,
                'hold_info': hold_info,
                'seller_name': seller_name,
                'product_type': product_type,
            })
        return result
    
    @api.model
    def _som_pack_for_quant(self, quant, product_id):
        """(empaque, m² por empaque) del producto para la compañía del
        material, o None si el producto se vende libre. Defensivo: sin el
        módulo de empaques instalado, None."""
        product = quant.product_id if quant else self.env['product.product'].browse(int(product_id)).exists()
        tmpl = product.product_tmpl_id if product else None
        if not tmpl or 'has_standard_pack' not in tmpl._fields or not tmpl.has_standard_pack:
            return None
        company = quant.company_id if quant and quant.company_id else self.env.company
        packs = tmpl._som_standard_packs_for_company(company) if hasattr(tmpl, '_som_standard_packs_for_company') else tmpl.sudo().standard_pack_ids.filtered('active')
        if not packs:
            return None
        default = tmpl.sudo().default_pack_id
        pack = default if default and default in packs else packs[:1]
        qpp = pack.qty_per_pack or 0.0
        return (pack, qpp) if qpp > 0 else None

    @staticmethod
    def _som_snap_quantity_to_pack(quantity, available, qpp):
        """Cantidad en empaques COMPLETOS: hacia abajo respecto a lo pedido y
        sin rebasar lo disponible. None si no cabe ni un empaque."""
        eps = 1e-6
        max_packs = int((available + eps) // qpp) if available > 0 else 0
        # Pedir menos de un empaque = un empaque (mínimo vendible).
        wanted = max(int((quantity + eps) // qpp), 1) if quantity > 0 else max_packs
        packs = min(wanted, max_packs)
        if packs < 1:
            return None
        return round(packs * qpp, 6)

    @api.model
    def add_to_cart(self, quant_id=None, lot_id=None, product_id=None, quantity=None, location_name=None, pack_choice=None):
        """Agregar item al carrito o actualizar cantidad si ya existe"""
        if not all([quant_id, lot_id, product_id, quantity is not None]):
            return {'success': False, 'message': 'Faltan parámetros'}

        # Validación temprana (antes solo reventaba hasta crear la cotización):
        # - placa completamente reservada en otra operación: NO entra al carrito;
        # - placa con hold: entra (puede ser para el mismo cliente, que aún no
        #   se conoce aquí) pero con AVISO de para quién está apartada.
        warning = ''
        # Movedor de Ubicaciones: puede agregar placas COMPROMETIDAS
        # (reservadas en venta/entrega, con hold, o en carrito de otro) para
        # trasladarlas de ubicación — la reserva fuerte se traspasa al bin
        # destino al validar el traslado.
        is_location_mover = self.env.user.has_group(
            'inventory_shopping_cart.group_cart_location_mover')
        quant = self.env['stock.quant'].sudo().browse(int(quant_id)).exists()
        if quant and not is_location_mover:
            free_qty = (quant.quantity or 0.0) - (quant.reserved_quantity or 0.0)
            if free_qty <= 0 and quant.lot_id:
                # La reserva puede venir SOLO de un traslado interno de
                # carrito/escáner abierto (reserva DÉBIL de reacomodo): esa
                # no impide cotizar la placa — se libera sola al crear la
                # venta. Se descuenta del reservado para el cálculo.
                weak_lines = self.env['stock.move.line'].sudo().search([
                    ('product_id', '=', quant.product_id.id),
                    ('lot_id', '=', quant.lot_id.id),
                    ('location_id', '=', quant.location_id.id),
                    ('state', 'in', ('assigned', 'partially_available')),
                    ('picking_id.picking_type_code', '=', 'internal'),
                    ('picking_id.origin', '=like', 'Carrito - %'),
                    ('picking_id.state', 'not in', ('done', 'cancel')),
                ])
                weak_reserved = sum(weak_lines.mapped('quantity'))
                free_qty += weak_reserved
            if free_qty <= 0:
                return {
                    'success': False,
                    'message': (
                        f'La placa {quant.lot_id.name or ""} ya está reservada '
                        'en otra operación (venta/entrega). No se puede agregar.'
                    ),
                }
            if getattr(quant, 'x_tiene_hold', False) and quant.x_hold_activo_id:
                hold_partner = quant.x_hold_activo_id.partner_id
                warning = (
                    f' ⚠ Ojo: apartada para {hold_partner.name}. Solo podrás '
                    'cotizarla a ese cliente.'
                )

        # ESTADO DE CARRITO ENTRE VENDEDORES: si el lote vive en el carrito
        # ACTIVO de otro usuario, no se puede tomar — se informa de quién es
        # y cuánto le queda de vigencia (24h sin movimiento lo libera).
        # El Movedor de Ubicaciones sí puede tomarlo: su fin es el traslado
        # físico, no la venta, y la reserva débil se traspasa al bin destino.
        foreign = (
            self.env['shopping.cart']
            if is_location_mover
            else self._som_active_entries_for_lots(
                [lot_id], exclude_user_id=self.env.user.id)
        )
        if foreign:
            entry = foreign[0]
            return {
                'success': False,
                'message': (
                    'El lote %s está EN EL CARRITO de %s desde %s '
                    '(le quedan %.1f h de vigencia). Si no lo convierte en '
                    'pedido, se liberará automáticamente.'
                ) % (
                    entry.quant_id.lot_id.name or '',
                    entry.user_id.name,
                    som_format_date(
                        fields.Datetime.context_timestamp(
                            self, entry.added_at or entry.create_date
                        ),
                        with_time=True,
                    ),
                    entry._som_hours_left(),
                ),
            }

        # EMPAQUE ESTÁNDAR: si el producto se vende por empaque, la cantidad
        # que entra al carrito se ajusta AQUÍ, al elegirla, a empaques
        # completos (nunca fracciones). Antes el carrito aceptaba cualquier
        # m² y la venta reventaba al final con "no es múltiplo exacto".
        pack_note = ''
        # El Movedor de Ubicaciones NO vende: toma placas comprometidas para
        # trasladarlas y etiquetarlas, tal cual están. La regla de empaques
        # es de VENTA y se aplica al vendedor (y como candado al crear la
        # orden/apartado), no al movimiento físico.
        pack_info = None if is_location_mover else self._som_pack_for_quant(quant, product_id)
        if pack_info:
            pack, qpp = pack_info
            free_avail = quant.quantity - quant.reserved_quantity if quant else float(quantity)
            eps = 1e-6
            max_packs = int((free_avail + eps) // qpp) if free_avail > 0 else 0
            pname = quant.product_id.display_name if quant else ''
            if max_packs < 1:
                return {
                    'success': False,
                    'message': (
                        'El producto %s se vende por empaque (%s = %g m²) y esta '
                        'pieza/lote solo tiene %.2f m² disponibles: no completa '
                        'ni un empaque.'
                    ) % (pname, pack.display_name, qpp, free_avail),
                }
            if pack_choice:
                # El vendedor ya decidió cuántos empaques.
                packs_n = max(1, min(int(pack_choice), max_packs))
                quantity = round(packs_n * qpp, 6)
            else:
                packs_f = float(quantity) / qpp
                exact = abs(packs_f - round(packs_f)) <= 0.001 and 1 <= round(packs_f) <= max_packs
                if not exact:
                    # No cuadra: el VENDEDOR decide a cuántos empaques ajustar.
                    low = int(packs_f + eps); high = low + 1
                    cands = sorted({n for n in (low, high) if 1 <= n <= max_packs} | ({max_packs} if float(quantity) > max_packs * qpp else set()))
                    if not cands:
                        cands = [1]
                    return {
                        'success': False,
                        'needs_pack_choice': True,
                        'message': (
                            '%s se vende por empaque (%s = %g m²). %.2f m² no es '
                            'un número exacto de empaques: elige cuántos quieres.'
                        ) % (pname, pack.display_name, qpp, float(quantity)),
                        'product_name': pname,
                        'pack_name': pack.display_name,
                        'qty_per_pack': qpp,
                        'requested': float(quantity),
                        'available': free_avail,
                        'max_packs': max_packs,
                        'options': [{'packs': n, 'qty': round(n * qpp, 6)} for n in cands],
                    }
                packs_n = int(round(packs_f))
                quantity = round(packs_n * qpp, 6)
            pack_note = ' = %s empaque(s) de %g m² (%s).' % (packs_n, qpp, pack.display_name)

        # Buscar si ya existe
        existing = self.search([('user_id', '=', self.env.user.id), ('quant_id', '=', quant_id)])
        
        if existing:
            # Si ya existe, actualizamos la cantidad
            existing.write({'quantity': quantity})
            return {'success': True, 'message': 'Cantidad actualizada' + warning + pack_note,
                    'quantity': quantity, 'adjusted': bool(pack_info)}

        # Si no existe, creamos
        self.create({
            'quant_id': quant_id,
            'lot_id': lot_id,
            'product_id': product_id,
            'quantity': quantity,
            'location_name': location_name or ''
        })
        return {'success': True, 'message': ('Agregado al carrito.' + warning) if warning else '' + pack_note, 'quantity': quantity, 'adjusted': bool(pack_info)}
    
    @api.model
    def remove_from_cart(self, quant_id):
        """Remover item del carrito"""
        item = self.search([('user_id', '=', self.env.user.id), ('quant_id', '=', quant_id)])
        if item:
            item.unlink()
            return {'success': True}
        return {'success': False}
    
    @api.model
    def remove_many_from_cart(self, quant_ids):
        """Quitar varios items del carrito del usuario (desde el diálogo)."""
        ids = [int(q) for q in (quant_ids or []) if q]
        if not ids:
            return {'success': False, 'removed': 0}
        items = self.search([('user_id', '=', self.env.user.id), ('quant_id', 'in', ids)])
        removed = len(items)
        items.unlink()
        return {'success': True, 'removed': removed}

    @api.model
    def clear_cart(self):
        """Limpiar carrito del usuario"""
        items = self.search([('user_id', '=', self.env.user.id)])
        items.unlink()
        return {'success': True}
    
    @api.model
    def remove_holds_from_cart(self):
        """Remover lotes con hold del carrito"""
        items = self.search([('user_id', '=', self.env.user.id)])
        removed = 0
        for item in items:
            if hasattr(item.quant_id, 'x_tiene_hold') and item.quant_id.x_tiene_hold:
                item.unlink()
                removed += 1
        return {'success': True, 'removed': removed}