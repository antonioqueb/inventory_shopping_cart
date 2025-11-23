# ./models/shopping_cart.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.models import Constraint  # Requerido para Odoo 19

class ShoppingCart(models.Model):
    _name = 'shopping.cart'
    _description = 'Carrito de Compras Persistente'
    
    user_id = fields.Many2one('res.users', string='Usuario', required=True, default=lambda self: self.env.user, index=True)
    quant_id = fields.Many2one('stock.quant', string='Quant', required=True, ondelete='cascade')
    lot_id = fields.Integer(string='Lote ID', required=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    quantity = fields.Float(string='Cantidad', required=True)
    location_name = fields.Char(string='Ubicación')
    added_at = fields.Datetime(string='Agregado', default=fields.Datetime.now)
    
    unique_user_quant = Constraint(
        'unique(user_id, quant_id)',
        'Este lote ya está en tu carrito'
    )
    
    @api.model
    def get_cart_items(self):
        """Obtener items del carrito del usuario actual"""
        items = self.search([('user_id', '=', self.env.user.id)])
        result = []
        for item in items:
            # Usar 'stock.lot' (correcto para Odoo 16+)
            lot = self.env['stock.lot'].browse(item.lot_id)
            if not lot.exists():
                continue
                
            hold_info = ''
            seller_name = ''
            # Verificamos si el quant tiene hold (depende de stock_lot_dimensions)
            if hasattr(item.quant_id, 'x_tiene_hold') and item.quant_id.x_tiene_hold and item.quant_id.x_hold_activo_id:
                hold = item.quant_id.x_hold_activo_id
                hold_info = item.quant_id.x_hold_para
                if hold.user_id:
                    seller_name = hold.user_id.name
            
            result.append({
                'id': item.quant_id.id,
                'lot_id': lot.id,
                'lot_name': lot.name,
                'product_id': item.product_id.id,
                'product_name': item.product_id.display_name,
                'quantity': item.quantity,
                'location_name': item.location_name,
                'tiene_hold': getattr(item.quant_id, 'x_tiene_hold', False),
                'hold_info': hold_info,
                'seller_name': seller_name
            })
        return result
    
    @api.model
    def add_to_cart(self, quant_id=None, lot_id=None, product_id=None, quantity=None, location_name=None):
        """Agregar item al carrito"""
        # Validación de parámetros (quantity=0 es válido, pero None no)
        if not all([quant_id, lot_id, product_id, quantity is not None]):
            return {'success': False, 'message': 'Faltan parámetros'}
        
        # Validación Python previa para evitar error de SQL
        existing = self.search([('user_id', '=', self.env.user.id), ('quant_id', '=', quant_id)])
        if existing:
            return {'success': False, 'message': 'Ya está en el carrito'}
        
        self.create({
            'quant_id': quant_id,
            'lot_id': lot_id,
            'product_id': product_id,
            'quantity': quantity,
            'location_name': location_name or ''
        })
        return {'success': True}
    
    @api.model
    def remove_from_cart(self, quant_id):
        """Remover item del carrito"""
        item = self.search([('user_id', '=', self.env.user.id), ('quant_id', '=', quant_id)])
        if item:
            item.unlink()
            return {'success': True}
        return {'success': False}
    
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