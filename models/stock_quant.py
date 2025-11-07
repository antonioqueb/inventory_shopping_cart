# ./models/stock_quant.py en inventory_shopping_cart
# -*- coding: utf-8 -*-
from odoo import models, api

class StockQuant(models.Model):
    _inherit = 'stock.quant'
    
    @api.model
    def get_current_user_info(self):
        """Obtener información del usuario actual"""
        return {
            'id': self.env.user.id,
            'name': self.env.user.name
        }
    
    @api.model
    def sync_cart_to_session(self, items):
        """Sincronizar carrito desde frontend a BD"""
        cart_model = self.env['shopping.cart']
        cart_model.clear_cart()
        
        for item in items:
            cart_model.add_to_cart(
                quant_id=item['id'],
                lot_id=item['lot_id'],
                product_id=item['product_id'],
                quantity=item['quantity'],
                location_name=item['location_name']
            )
        
        return {'success': True}
    
    @api.model
    def create_holds_from_cart(self, partner_id=None, project_id=None, 
                               architect_id=None, selected_lots=None, 
                               notes=None, currency_code='USD', 
                               product_prices=None):
        """Delegar creación de holds al módulo stock_lot_dimensions"""
        return self.env['stock.quant'].create_holds_from_cart(
            partner_id=partner_id,
            project_id=project_id,
            architect_id=architect_id,
            selected_lots=selected_lots,
            notes=notes,
            currency_code=currency_code,
            product_prices=product_prices
        )