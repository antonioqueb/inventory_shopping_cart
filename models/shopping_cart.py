# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ShoppingCart(models.Model):
    _name = 'shopping.cart'
    _description = 'Carrito de Compras Persistente'
    
    user_id = fields.Many2one('res.users', string='Usuario', required=True, default=lambda self: self.env.user, index=True)
    quant_id = fields.Many2one('stock.quant', string='Quant', required=True, ondelete='cascade')
    lot_id = fields.Many2one('stock.production.lot', string='Lote', required=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    quantity = fields.Float(string='Cantidad', required=True)
    location_name = fields.Char(string='Ubicación')
    added_at = fields.Datetime(string='Agregado', default=fields.Datetime.now)
    
    _sql_constraints = [
        ('unique_user_quant', 'unique(user_id, quant_id)', 'Este lote ya está en tu carrito')
    ]
    
    @api.model
    def get_cart_items(self):
        """Obtener items del carrito del usuario actual"""
        items = self.search([('user_id', '=', self.env.user.id)])
        return [{
            'id': item.quant_id.id,
            'lot_id': item.lot_id.id,
            'lot_name': item.lot_id.name,
            'product_id': item.product_id.id,
            'product_name': item.product_id.display_name,
            'quantity': item.quantity,
            'location_name': item.location_name,
            'tiene_hold': item.quant_id.x_tiene_hold,
            'hold_info': item.quant_id.x_hold_para if item.quant_id.x_tiene_hold else ''
        } for item in items]
    
    @api.model
    def add_to_cart(self, quant_id=None, lot_id=None, product_id=None, quantity=None, location_name=None):
        """Agregar item al carrito"""
        if not all([quant_id, lot_id, product_id, quantity is not None]):
            return {'success': False, 'message': 'Faltan parámetros'}
        
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
            if item.quant_id.x_tiene_hold:
                item.unlink()
                removed += 1
        return {'success': True, 'removed': removed}