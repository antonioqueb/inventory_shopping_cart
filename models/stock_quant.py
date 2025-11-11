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
        """
        Crear múltiples apartados desde el carrito de compras
        """
        if not selected_lots or not partner_id:
            return {'success': 0, 'errors': 1, 'failed': [{'error': 'Faltan parámetros requeridos'}]}
        
        success_count = 0
        error_count = 0
        failed_lots = []
        
        for quant_id in selected_lots:
            try:
                quant = self.browse(quant_id)
                
                if not quant.exists() or not quant.lot_id:
                    error_count += 1
                    failed_lots.append({
                        'lot_name': f'Quant {quant_id}',
                        'error': 'Lote no encontrado'
                    })
                    continue
                
                # Verificar si ya tiene hold
                if hasattr(quant, 'x_tiene_hold') and quant.x_tiene_hold:
                    error_count += 1
                    failed_lots.append({
                        'lot_name': quant.lot_id.name,
                        'error': 'Ya tiene apartado activo'
                    })
                    continue
                
                # Construir notas con precios
                full_notes = notes or ''
                
                if product_prices and isinstance(product_prices, dict):
                    product_id = quant.product_id.id
                    if str(product_id) in product_prices:
                        price = product_prices[str(product_id)]
                        full_notes += f'\n\n=== PRECIO ({currency_code}) ===\n'
                        full_notes += f'• {quant.product_id.display_name}: {price:.2f} {currency_code}/m²\n'
                
                # Calcular fecha de expiración (5 días hábiles)
                from datetime import datetime, timedelta
                fecha_inicio = datetime.now()
                fecha_expiracion = fecha_inicio
                dias_agregados = 0
                
                while dias_agregados < 5:
                    fecha_expiracion += timedelta(days=1)
                    if fecha_expiracion.weekday() < 5:  # Lunes a Viernes
                        dias_agregados += 1
                
                # Preparar valores para crear el hold
                hold_vals = {
                    'lot_id': quant.lot_id.id,
                    'partner_id': partner_id,
                    'user_id': self.env.user.id,
                    'fecha_inicio': fecha_inicio,
                    'fecha_expiracion': fecha_expiracion,
                    'notas': full_notes,
                }
                
                # Agregar campos opcionales
                hold_model = self.env['stock.lot.hold']
                if 'quant_id' in hold_model._fields:
                    hold_vals['quant_id'] = quant.id
                if 'project_id' in hold_model._fields and project_id:
                    hold_vals['project_id'] = project_id
                if 'arquitecto_id' in hold_model._fields and architect_id:
                    hold_vals['arquitecto_id'] = architect_id
                
                # Crear el hold
                hold_model.create(hold_vals)
                success_count += 1
                
            except Exception as e:
                error_count += 1
                failed_lots.append({
                    'lot_name': quant.lot_id.name if quant.exists() and quant.lot_id else f'Quant {quant_id}',
                    'error': str(e)
                })
        
        return {
            'success': success_count,
            'errors': error_count,
            'failed': failed_lots
        }