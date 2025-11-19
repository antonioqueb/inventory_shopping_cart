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
    def check_sales_permissions(self):
        """Verifica si el usuario tiene permisos de ventas"""
        return self.env.user.has_group('sales_team.group_sale_salesman') or \
               self.env.user.has_group('sales_team.group_sale_salesman_all_leads') or \
               self.env.user.has_group('sales_team.group_sale_manager')
    
    @api.model
    def check_inventory_permissions(self):
        """Verifica si el usuario tiene permisos de inventario"""
        return self.env.user.has_group('stock.group_stock_user')
    
    @api.model
    def get_internal_locations(self, search_term=''):
        """Obtener ubicaciones internas para traslados"""
        domain = [('usage', '=', 'internal')]
        
        if search_term:
            domain = ['&'] + domain + [
                '|', ('name', 'ilike', search_term),
                ('complete_name', 'ilike', search_term)
            ]
        
        locations = self.env['stock.location'].search(domain, limit=50)
        
        return [{
            'id': loc.id,
            'name': loc.name,
            'complete_name': loc.complete_name,
            'parent_name': loc.location_id.name if loc.location_id else ''
        } for loc in locations]
    
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
        
        # ✅ VERIFICAR SI REQUIERE AUTORIZACIÓN (solo si no viene de una autorización aprobada)
        if not self.env.context.get('skip_authorization_check'):
            auth_check = self.env['product.template'].check_price_authorization_needed(
                product_prices, 
                currency_code
            )
            
            if auth_check['needs_authorization']:
                # Agrupar lotes por producto
                product_groups = {}
                for quant_id in selected_lots:
                    quant = self.browse(quant_id)
                    if not quant.exists() or not quant.lot_id:
                        continue
                        
                    pid = quant.product_id.id
                    if pid not in product_groups:
                        product_groups[pid] = {
                            'name': quant.product_id.display_name,
                            'lots': [],
                            'total_quantity': 0
                        }
                    
                    product_groups[pid]['lots'].append({
                        'id': quant_id,
                        'lot_name': quant.lot_id.name,
                        'quantity': quant.quantity
                    })
                    product_groups[pid]['total_quantity'] += quant.quantity
                
                result = self.create_price_authorization(
                    operation_type='hold',
                    partner_id=partner_id,
                    project_id=project_id,
                    selected_lots=selected_lots,
                    currency_code=currency_code,
                    product_prices=product_prices,
                    product_groups=product_groups,
                    notes=notes,
                    architect_id=architect_id
                )
                
                if result['success']:
                    return {
                        'success': False,
                        'needs_authorization': True,
                        'authorization_id': result['authorization_id'],
                        'authorization_name': result['authorization_name'],
                        'message': f'Solicitud de autorización {result["authorization_name"]} creada. Espere aprobación del autorizador.'
                    }
        
        # ✅ DETERMINAR QUÉ VENDEDOR USAR
        # Si viene del contexto (desde autorización), usar ese
        # Si no, usar el usuario actual
        seller_id = self.env.context.get('force_seller_id', self.env.user.id)
        
        # ✅ SI NO REQUIERE AUTORIZACIÓN, CREAR APARTADOS NORMALMENTE
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
                    'user_id': seller_id,  # ✅ USAR EL VENDEDOR CORRECTO
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
    
    @api.model
    def create_price_authorization(self, operation_type, partner_id, project_id, 
                                   selected_lots, currency_code, product_prices, 
                                   product_groups, notes=None, architect_id=None):
        """Crea solicitud de autorización de precio"""
        
        # ✅ NORMALIZAR: Convertir todas las claves de product_prices a string
        if isinstance(product_prices, dict):
            product_prices = {str(k): v for k, v in product_prices.items()}
        
        # ✅ CREAR LA AUTORIZACIÓN
        auth = self.env['price.authorization'].create({
            'seller_id': self.env.user.id,
            'operation_type': operation_type,
            'partner_id': partner_id,
            'project_id': project_id,
            'currency_code': currency_code,
            'notes': notes or '',
            'temp_data': {
                'selected_lots': selected_lots,
                'product_prices': product_prices,
                'product_groups': product_groups,
                'architect_id': architect_id
            }
        })
        
        # ✅ CREAR LÍNEAS CON EL PRECIO SOLICITADO CORRECTO
        for product_id_str, group in product_groups.items():
            product_id = int(product_id_str)
            product = self.env['product.product'].browse(product_id)
            
            # Obtener precios según divisa
            if currency_code == 'USD':
                medium_price = product.product_tmpl_id.x_price_usd_2
                minimum_price = product.product_tmpl_id.x_price_usd_3
            else:  # MXN
                medium_price = product.product_tmpl_id.x_price_mxn_2
                minimum_price = product.product_tmpl_id.x_price_mxn_3
            
            # ✅ OBTENER EL PRECIO SOLICITADO CORRECTAMENTE (ahora las claves coinciden)
            requested_price = float(product_prices.get(str(product_id), 0))
            
            # ✅ CREAR LÍNEA CON requested_price Y authorized_price
            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': product_id,
                'quantity': group['total_quantity'],
                'lot_count': len(group['lots']),
                'requested_price': requested_price,  # ✅ Precio que pidió el vendedor
                'authorized_price': requested_price,  # ✅ Inicialmente igual, el autorizador puede cambiarlo
                'medium_price': medium_price,
                'minimum_price': minimum_price
            })
        
        return {
            'success': True,
            'authorization_id': auth.id,
            'authorization_name': auth.name
        }