# ./models/stock_quant.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta


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

    # === NUEVA FUNCIONALIDAD: GENERADOR ZPL ===
    @api.model
    def generate_zpl_labels(self, selected_lots, label_format):
        """
        Genera código ZPL para imprimir etiquetas de lotes.
        """
        if not selected_lots:
            return {'success': False, 'message': 'No hay lotes seleccionados'}
        
        quants = self.browse(selected_lots)
        zpl_code = ""
        
        for quant in quants:
            lot = quant.lot_id
            product_name = quant.product_id.name[:40] if quant.product_id.name else ''
            lot_name = lot.name or ''
            
            dim_str = ""
            if hasattr(lot, 'x_alto') and hasattr(lot, 'x_ancho'):
                dim_str = f"{lot.x_alto}x{lot.x_ancho} cm"
            
            zpl_code += "^XA^CI28"
            
            if label_format == '10x5':
                zpl_code += "^FO20,30^A0N,40,40^FD" + product_name + "^FS"
                zpl_code += "^FO20,80^A0N,35,35^FDLote: " + lot_name + "^FS"
                zpl_code += "^FO20,120^A0N,30,30^FD" + dim_str + "^FS"
                zpl_code += "^FO40,180^BY2,2,100^BCN,100,Y,N,N^FD" + lot_name + "^FS"
                
            elif label_format == '17.5x1':
                text_line = f"{lot_name} - {product_name} {dim_str}"
                zpl_code += "^FO20,20^A0N,30,30^FD" + text_line + "^FS"
                
            elif label_format == '20x10':
                zpl_code += "^FO50,50^A0N,70,70^FD" + product_name + "^FS"
                zpl_code += "^FO50,150^A0N,50,50^FDLote: " + lot_name + "^FS"
                zpl_code += "^FO50,220^A0N,50,50^FDDimensiones: " + dim_str + "^FS"
                if hasattr(lot, 'x_grosor'):
                    zpl_code += f"^FO50,290^A0N,50,50^FDGrosor: {lot.x_grosor} cm^FS"
                zpl_code += f"^FO800,150^A0N,50,50^FDArea: {quant.quantity} m2^FS"
                zpl_code += "^FO100,400^BY4,3,200^BCN,200,Y,N,N^FD" + lot_name + "^FS"
                zpl_code += "^FO20,20^GB1550,760,4^FS"

            zpl_code += "^XZ"
            
        return {
            'success': True,
            'zpl_data': zpl_code,
            'filename': f'etiquetas_{label_format}_{fields.Date.today()}.zpl'
        }

    def _get_partner_delivery_address(self, partner):
        """Construir dirección de entrega del cliente"""
        if not partner: return ''
        address_parts = []
        if partner.street: address_parts.append(partner.street)
        if partner.street2: address_parts.append(partner.street2)
        city_parts = []
        if partner.city: city_parts.append(partner.city)
        if partner.state_id: city_parts.append(partner.state_id.name)
        if partner.zip: city_parts.append(f"C.P. {partner.zip}")
        if city_parts: address_parts.append(', '.join(city_parts))
        if partner.country_id: address_parts.append(partner.country_id.name)
        return '\n'.join(address_parts) if address_parts else ''

    @api.model
    def create_holds_from_cart(
        self,
        partner_id=None,
        project_id=None,
        architect_id=None,
        selected_lots=None,
        notes=None,
        currency_code='USD',
        product_prices=None,
        services=None,
        backorder_items=None, # ✅ NUEVO PARAMETRO
    ):
        """
        Crear múltiples apartados desde el carrito.
        Soporta:
        1. Lotes Físicos (selected_lots) -> Crea stock.lot.hold y líneas con lot_id
        2. Material por Pedido (backorder_items) -> Crea líneas SIN lot_id (solo financiero)
        3. Servicios (services) -> Crea líneas tipo servicio
        """
        has_lots = selected_lots and len(selected_lots) > 0
        has_services = services and len(services) > 0
        has_backorders = backorder_items and len(backorder_items) > 0

        if not partner_id or (not has_lots and not has_services and not has_backorders):
            return {
                'success': 0,
                'errors': 1,
                'failed': [{'error': 'Faltan parámetros requeridos o selección de items'}]
            }

        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            currency = self.env.company.currency_id

        # ✅ VERIFICAR AUTORIZACIÓN (Solo para lotes físicos, que son los que tienen precio medio definido)
        if has_lots and not self.env.context.get('skip_authorization_check'):
            auth_check = self.env['product.template'].check_price_authorization_needed(product_prices, currency_code)
            if auth_check.get('needs_authorization'):
                # (Lógica de autorización igual al original...)
                product_groups = {}
                for quant_id in selected_lots:
                    quant = self.browse(quant_id)
                    if not quant.exists() or not quant.lot_id: continue
                    pid = quant.product_id.id
                    if pid not in product_groups: product_groups[pid] = {'name': quant.product_id.display_name, 'lots': [], 'total_quantity': 0}
                    product_groups[pid]['lots'].append({'id': quant_id, 'lot_name': quant.lot_id.name, 'quantity': quant.quantity})
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
                    architect_id=architect_id,
                )
                if result.get('success'):
                    return { 'success': False, 'needs_authorization': True, 'authorization_id': result['authorization_id'], 'authorization_name': result['authorization_name'], 'message': f'Solicitud {result["authorization_name"]} creada.' }

        full_notes = notes or ''
        if product_prices and isinstance(product_prices, dict):
            normalized_prices = {str(k): float(v) for k, v in product_prices.items()}
            # Agregar precios de lotes a notas
            price_by_product = {}
            if has_lots:
                for quant_id in selected_lots:
                    quant = self.browse(quant_id)
                    if not quant.exists(): continue
                    pid = quant.product_id.id
                    if str(pid) in normalized_prices and pid not in price_by_product:
                        price_by_product[pid] = { 'name': quant.product_id.display_name, 'price': normalized_prices[str(pid)] }
            if price_by_product:
                full_notes += '\n\n=== PRECIOS LOTES EXISTENTES ({}) ===\n'.format(currency_code)
                for data in price_by_product.values():
                    full_notes += f'• {data["name"]}: {data["price"]:.2f} {currency_code}/m²\n'

        fecha_orden = datetime.now()
        fecha_expiracion = fecha_orden
        dias_agregados = 0
        while dias_agregados < 5:
            fecha_expiracion += timedelta(days=1)
            if fecha_expiracion.weekday() < 5: dias_agregados += 1

        partner = self.env['res.partner'].browse(partner_id)
        
        hold_order_vals = {
            'partner_id': partner_id,
            'user_id': self.env.context.get('force_seller_id', self.env.user.id),
            'project_id': project_id,
            'arquitecto_id': architect_id,
            'notas': full_notes,
            'company_id': self.env.company.id,
            'fecha_orden': fecha_orden,
            'fecha_expiracion': fecha_expiracion,
            'currency_id': currency.id,
            'delivery_address': self._get_partner_delivery_address(partner),
        }
        order = self.env['stock.lot.hold.order'].create(hold_order_vals)

        normalized_prices = {}
        if product_prices and isinstance(product_prices, dict):
            normalized_prices = {str(k): float(v) for k, v in product_prices.items()}

        success_count = 0
        error_count = 0
        failed_lots = []

        # 1. LOTES FÍSICOS (Con Hold)
        if has_lots:
            for quant_id in selected_lots:
                try:
                    quant = self.browse(quant_id)
                    if not quant.exists() or not quant.lot_id: continue
                    if hasattr(quant, 'x_tiene_hold') and quant.x_tiene_hold:
                        error_count += 1
                        failed_lots.append({'lot_name': quant.lot_id.name, 'error': 'Ya tiene apartado'})
                        continue

                    product_id = quant.product_id.id
                    precio_unitario = normalized_prices.get(str(product_id), 0.0)

                    self.env['stock.lot.hold.order.line'].create({
                        'order_id': order.id,
                        'quant_id': quant.id,
                        'lot_id': quant.lot_id.id,
                        'product_id': product_id,
                        'precio_unitario': precio_unitario,
                    })
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    failed_lots.append({'lot_name': f'Quant {quant_id}', 'error': str(e)})

        # 2. BACKORDERS (NUEVO - Sin lote, solo cantidad financiera)
        if has_backorders:
            for item in backorder_items:
                try:
                    self.env['stock.lot.hold.order.line'].create({
                        'order_id': order.id,
                        'product_id': int(item['product_id']),
                        'lot_id': False,
                        'quant_id': False,
                        'cantidad_m2': float(item['quantity']),
                        'precio_unitario': float(item['price_unit']),
                    })
                except Exception as e:
                    error_count += 1
                    failed_lots.append({'lot_name': f"Pedido ID {item.get('product_id')}", 'error': str(e)})

        # 3. SERVICIOS
        if has_services:
            for service in services:
                try:
                    self.env['stock.lot.hold.order.line'].create({
                        'order_id': order.id,
                        'product_id': int(service['product_id']),
                        'lot_id': False,
                        'quant_id': False,
                        'cantidad_m2': float(service['quantity']),
                        'precio_unitario': float(service['price_unit']),
                    })
                except Exception as e:
                    error_count += 1
                    failed_lots.append({'lot_name': f"Servicio ID {service.get('product_id')}", 'error': str(e)})

        has_content = success_count > 0 or has_backorders or has_services
        if has_content:
            try:
                order.action_confirm()
            except Exception as e:
                return {'success': 0, 'errors': 1, 'failed': [{'error': f'Error confirmando: {str(e)}'}]}
        else:
            if order: order.unlink()

        return {
            'success': success_count,
            'errors': error_count,
            'failed': failed_lots,
            'order_id': order.id if order else None,
            'order_name': order.name if order else None,
        }

    @api.model
    def create_price_authorization(self, operation_type, partner_id, project_id, selected_lots, currency_code, product_prices, product_groups, notes=None, architect_id=None):
        """Crea solicitud de autorización de precio"""
        if isinstance(product_prices, dict):
            product_prices = {str(k): v for k, v in product_prices.items()}

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
                'architect_id': architect_id,
            },
        })

        for product_id_key, group in product_groups.items():
            product_id = int(product_id_key)
            product = self.env['product.product'].browse(product_id)
            if currency_code == 'USD':
                medium_price = product.product_tmpl_id.x_price_usd_2
                minimum_price = product.product_tmpl_id.x_price_usd_3
            else:
                medium_price = product.product_tmpl_id.x_price_mxn_2
                minimum_price = product.product_tmpl_id.x_price_mxn_3

            requested_price = float(product_prices.get(str(product_id), 0))

            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': product_id,
                'quantity': group['total_quantity'],
                'lot_count': len(group['lots']),
                'requested_price': requested_price,
                'authorized_price': requested_price,
                'medium_price': medium_price,
                'minimum_price': minimum_price,
            })

        return {'success': True, 'authorization_id': auth.id, 'authorization_name': auth.name}