# ./models/stock_quant.py
# -*- coding: utf-8 -*-
from odoo import models, api, fields

class StockQuant(models.Model):
    _inherit = 'stock.quant'
    
    @api.model
    def create_holds_from_cart(self, partner_id=None, project_id=None, architect_id=None, 
                                selected_lots=None, notes=None):
        """Crear holds desde el carrito con validación completa"""
        if not partner_id or not selected_lots:
            return {
                'success': 0, 
                'errors': 1, 
                'holds': [], 
                'failed': [{'error': 'Parámetros inválidos'}]
            }
        
        if not project_id:
            return {
                'success': 0,
                'errors': 1,
                'holds': [],
                'failed': [{'error': 'Debe seleccionar un proyecto'}]
            }
        
        if not architect_id:
            return {
                'success': 0,
                'errors': 1,
                'holds': [],
                'failed': [{'error': 'Debe seleccionar un arquitecto'}]
            }
        
        holds_created = []
        errors = []
        
        # Calcular fecha de expiración (5 días hábiles)
        from datetime import timedelta
        fecha_inicio = fields.Datetime.now()
        fecha_actual = fecha_inicio
        dias_agregados = 0
        
        while dias_agregados < 5:
            fecha_actual += timedelta(days=1)
            if fecha_actual.weekday() < 5:  # Lunes a viernes
                dias_agregados += 1
        
        fecha_expiracion = fecha_actual
        
        for quant_id in selected_lots:
            quant = self.browse(quant_id)
            
            if not quant.exists() or not quant.lot_id:
                errors.append({
                    'quant_id': quant_id, 
                    'error': 'Quant no válido o sin lote'
                })
                continue
            
            if quant.x_tiene_hold:
                errors.append({
                    'lot_name': quant.lot_id.name, 
                    'error': f'Ya apartado para {quant.x_hold_para}'
                })
                continue
            
            try:
                hold = self.env['stock.lot.hold'].create({
                    'lot_id': quant.lot_id.id,
                    'quant_id': quant.id,
                    'partner_id': partner_id,
                    'user_id': self.env.user.id,
                    'project_id': project_id,
                    'arquitecto_id': architect_id,
                    'fecha_inicio': fecha_inicio,
                    'fecha_expiracion': fecha_expiracion,
                    'notas': notes or 'Apartado desde carrito',
                })
                
                holds_created.append({
                    'lot_name': quant.lot_id.name,
                    'hold_id': hold.id,
                    'expira': hold.fecha_expiracion.strftime('%d/%m/%Y %H:%M')
                })
            except Exception as e:
                errors.append({
                    'lot_name': quant.lot_id.name, 
                    'error': str(e)
                })
        
        return {
            'success': len(holds_created),
            'errors': len(errors),
            'holds': holds_created,
            'failed': errors
        }