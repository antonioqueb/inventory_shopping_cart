# ./models/stock_quant.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import math


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
    def _get_pricelist_for_currency(self, currency_code='USD'):
        currency_code = currency_code or 'USD'
        return self.env['product.pricelist'].search([
            ('name', '=', currency_code),
        ], limit=1)

    @api.model
    def _compute_product_sale_price(self, product, currency_code='USD', partner_id=None, quantity=1.0):
        """
        Calcula un precio de venta de catálogo/pricelist para productos no sujetos
        a la escalera especial de mármol, principalmente servicios.

        No confía en el valor enviado por el frontend.
        """
        quantity = float(quantity or 1.0)
        if quantity <= 0:
            quantity = 1.0

        partner = self.env['res.partner'].browse(partner_id) if partner_id else self.env['res.partner']
        pricelist = self._get_pricelist_for_currency(currency_code)
        price = 0.0

        if product and product.exists() and pricelist:
            try:
                price = pricelist._get_product_price(product, quantity, partner=partner if partner else False)
            except TypeError:
                try:
                    price = pricelist.get_product_price(product, quantity, partner if partner else False)
                except Exception:
                    price = 0.0
            except Exception:
                price = 0.0

        if price <= 0 and product and product.exists():
            price = getattr(product, 'lst_price', 0.0) or getattr(product, 'list_price', 0.0) or 0.0

            # Si no hubo lista de precios y la moneda solicitada es distinta a la de compañía,
            # convertir el precio base de la compañía a la moneda solicitada.
            currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
            company_currency = self.env.company.currency_id
            if currency and company_currency and currency != company_currency:
                try:
                    price = company_currency._convert(
                        price,
                        currency,
                        self.env.company,
                        fields.Date.today(),
                    )
                except Exception:
                    pass

        return math.ceil(float(price or 0.0))

    @api.model
    def get_sale_price_for_product(self, product_id=None, currency_code='USD', partner_id=None, quantity=1.0):
        """
        Endpoint RPC para que los wizards carguen precios de servicios desde backend.
        """
        if not product_id:
            return {
                'price_unit': 0.0,
                'currency_code': currency_code or 'USD',
            }

        product = self.env['product.product'].browse(int(product_id))
        if not product.exists():
            return {
                'price_unit': 0.0,
                'currency_code': currency_code or 'USD',
            }

        price_unit = self._compute_product_sale_price(
            product,
            currency_code=currency_code,
            partner_id=partner_id,
            quantity=quantity,
        )

        return {
            'product_id': product.id,
            'price_unit': price_unit,
            'currency_code': currency_code or 'USD',
        }

    @api.model
    def _normalize_services_for_hold(self, services=None, currency_code='USD', partner_id=None):
        """
        Fuerza precios de servicios desde backend para evitar que el usuario
        capture manualmente el precio unitario del servicio en el apartado.
        """
        normalized = []
        for service in (services or []):
            product_id = service.get('product_id')
            if not product_id:
                continue

            product = self.env['product.product'].browse(int(product_id))
            if not product.exists():
                continue

            qty = float(service.get('quantity') or 1.0)
            if qty <= 0:
                qty = 1.0

            price_unit = self._compute_product_sale_price(
                product,
                currency_code=currency_code,
                partner_id=partner_id,
                quantity=qty,
            )

            normalized.append({
                'product_id': product.id,
                'quantity': qty,
                'price_unit': price_unit,
            })

        return normalized

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

    # ============================================================
    # CANTIDADES SELECCIONADAS DESDE CARRITO / AUTORIZACIÓN
    # ============================================================

    def _resolve_selected_quantities(self, selected_lots=None, selected_quantities=None):
        """
        Resuelve la cantidad realmente seleccionada por quant.

        Prioridad:
        1. selected_quantities guardado en autorización.
        2. shopping.cart del vendedor actual.
        3. quantity completo del quant.

        Esto es crítico para formatos/piezas parciales, porque el hold no debe
        tomar siempre la cantidad completa del quant.
        """
        selected_lots = selected_lots or []
        clean_quant_ids = []

        for quant_id in selected_lots:
            try:
                clean_quant_ids.append(int(quant_id))
            except Exception:
                continue

        qty_by_quant = {}

        if isinstance(selected_quantities, dict):
            for key, value in selected_quantities.items():
                try:
                    qty_by_quant[int(key)] = float(value or 0.0)
                except Exception:
                    continue

        cart_owner_id = self.env.context.get('force_seller_id') or self.env.user.id

        if clean_quant_ids:
            cart_items = self.env['shopping.cart'].search([
                ('user_id', '=', cart_owner_id),
                ('quant_id', 'in', clean_quant_ids),
            ])

            for item in cart_items:
                qty_by_quant[item.quant_id.id] = item.quantity or 0.0

        for quant in self.browse(clean_quant_ids):
            if quant.id not in qty_by_quant:
                qty_by_quant[quant.id] = quant.quantity or 0.0

        return qty_by_quant

    # === GENERADOR ZPL ===

    @api.model
    def generate_zpl_labels(self, selected_lots, label_format):
        """
        Genera código ZPL para imprimir etiquetas de lotes.
        """
        if not selected_lots:
            return {'success': False, 'message': 'No hay lotes seleccionados'}

        quants = self.browse(selected_lots)
        zpl_code = ""

        # ── Canto/Lomo 17.5x1: 4 etiquetas por página, formato especial ──
        if label_format == '17.5x1':
            zpl_code = self._generate_canto_lomo_zpl(quants)
        else:
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

    def _generate_canto_lomo_zpl(self, quants):
        """
        Genera etiquetas formato 17.5x1 cm (canto/lomo).
        4 etiquetas por página ^XA..^XZ, dispuestas en 4 columnas verticales.
        Offset X entre columnas: 176 dots.
        """
        zpl = ""
        col_offset = 176

        for i in range(0, len(quants), 4):
            batch = quants[i:i + 4]
            zpl += "^XA\n^PW720\n^LL1500\n^CI28\n"

            for idx, quant in enumerate(batch):
                x = idx * col_offset
                lot = quant.lot_id
                product = quant.product_id

                lot_name = (lot.name or '').strip()

                if '-' in lot_name:
                    lot_prefix, lot_suffix = lot_name.rsplit('-', 1)
                else:
                    lot_prefix, lot_suffix = lot_name, ''

                product_name = (product.name or '').strip()
                if len(product_name) > 45:
                    if product_name[45] == ' ' or product_name[:45].endswith(' '):
                        product_name = product_name[:45].rstrip()
                    else:
                        product_name = product_name[:45] + '...'

                alto_raw = getattr(lot, 'x_alto', 0) or 0
                ancho_raw = getattr(lot, 'x_ancho', 0) or 0
                alto_m = alto_raw / 100.0 if alto_raw > 10 else alto_raw
                ancho_m = ancho_raw / 100.0 if ancho_raw > 10 else ancho_raw
                area = quant.quantity or 0
                dim_line = f"{alto_m:.2f} x {ancho_m:.2f} = {area:.2f} M2"

                lote_origen = (
                    getattr(lot, 'x_lote_origen', None)
                    or getattr(lot, 'x_bloque', None)
                    or getattr(lot, 'x_origen', None)
                    or lot_name
                )
                if hasattr(lote_origen, 'name'):
                    lote_origen = lote_origen.name
                lote_origen = str(lote_origen or '').strip()

                origen = '( SOM )'

                zpl += f"^FO{26 + x},20^A0N,43,38^FB160,1,0,C^FD{origen}^FS\n"
                zpl += f"^FO{18 + x},75^A0N,35,37^FB160,1,0,C^FD{lot_prefix}^FS\n"
                zpl += f"^FO{28 + x},130^A0N,78,78^FB160,1,0,C^FD{lot_suffix}^FS\n"
                zpl += f"^FO{133 + x},232^A0R,32,32^FD{product_name}^FS\n"
                zpl += f"^FO{88 + x},232^A0R,32,32^FD{dim_line}^FS\n"
                zpl += f"^FO{38 + x},232^A0R,32,32^FD{lote_origen}^FS\n"
                zpl += f"^FO{12 + x},1017^BY3,2,154^BCB,154,N,N,N^FD{lot_name}^FS\n"

            zpl += "^XZ\n"

        return zpl

    def _get_partner_delivery_address(self, partner):
        """Construir dirección de entrega del cliente"""
        if not partner:
            return ''

        address_parts = []

        if partner.street:
            address_parts.append(partner.street)
        if partner.street2:
            address_parts.append(partner.street2)

        city_parts = []
        if partner.city:
            city_parts.append(partner.city)
        if partner.state_id:
            city_parts.append(partner.state_id.name)
        if partner.zip:
            city_parts.append(f"C.P. {partner.zip}")

        if city_parts:
            address_parts.append(', '.join(city_parts))

        if partner.country_id:
            address_parts.append(partner.country_id.name)

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
        backorder_items=None,
        selected_quantities=None,
    ):
        """
        Crear múltiples apartados desde el carrito.

        Soporta:
        1. Lotes Físicos selected_lots -> crea stock.lot.hold.order y líneas con lot_ids.
        2. Material por Pedido backorder_items -> crea líneas sin lot_id.
        3. Servicios services -> crea líneas tipo servicio.

        Correcciones:
        - Respeta cantidades parciales seleccionadas desde carrito.
        - Calcula fecha de expiración desde stock.lot.hold.order.
        - Crea líneas con cantidad_m2, precio_unitario, subtotal y selector de precio.
        """
        selected_lots = selected_lots or []
        product_prices = product_prices or {}
        services = self._normalize_services_for_hold(
            services=services,
            currency_code=currency_code,
            partner_id=partner_id,
        )
        backorder_items = backorder_items or []

        has_lots = bool(selected_lots)
        has_services = bool(services)
        has_backorders = bool(backorder_items)

        if not partner_id or (not has_lots and not has_services and not has_backorders):
            return {
                'success': 0,
                'errors': 1,
                'failed': [{'error': 'Faltan parámetros requeridos o selección de items'}]
            }

        selected_qty_by_quant = self._resolve_selected_quantities(
            selected_lots=selected_lots,
            selected_quantities=selected_quantities,
        )

        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            currency = self.env.company.currency_id

        # ================================================================
        # VERIFICAR AUTORIZACIÓN — LOTES FÍSICOS Y PEDIDOS SIN EXISTENCIA
        # ================================================================
        auth_price_map = {
            str(k): float(v or 0.0)
            for k, v in (product_prices or {}).items()
        }

        for item in backorder_items:
            try:
                product_id = int(item.get('product_id'))
                auth_price_map[str(product_id)] = float(item.get('price_unit') or 0.0)
            except Exception:
                continue

        if (has_lots or has_backorders) and not self.env.context.get('skip_authorization_check'):
            auth_check = self.env['product.template'].check_price_authorization_needed(
                auth_price_map,
                currency_code
            )

            if auth_check.get('needs_authorization'):
                product_groups = {}

                for quant_id in selected_lots:
                    quant = self.browse(int(quant_id))
                    if not quant.exists() or not quant.lot_id:
                        continue

                    pid = quant.product_id.id
                    selected_qty = selected_qty_by_quant.get(quant.id, quant.quantity or 0.0)

                    if pid not in product_groups:
                        product_groups[pid] = {
                            'name': quant.product_id.display_name,
                            'lots': [],
                            'total_quantity': 0.0,
                        }

                    product_groups[pid]['lots'].append({
                        'id': quant.id,
                        'lot_name': quant.lot_id.name,
                        'quantity': selected_qty,
                    })
                    product_groups[pid]['total_quantity'] += selected_qty

                for item in backorder_items:
                    try:
                        product_id = int(item.get('product_id'))
                    except Exception:
                        continue

                    product = self.env['product.product'].browse(product_id)
                    if not product.exists():
                        continue

                    if product_id not in product_groups:
                        product_groups[product_id] = {
                            'name': product.display_name,
                            'lots': [],
                            'total_quantity': 0.0,
                        }

                    product_groups[product_id]['total_quantity'] += float(item.get('quantity') or 0.0)

                result = self.create_price_authorization(
                    operation_type='hold',
                    partner_id=partner_id,
                    project_id=project_id,
                    selected_lots=selected_lots,
                    currency_code=currency_code,
                    product_prices=auth_price_map,
                    product_groups=product_groups,
                    notes=notes,
                    architect_id=architect_id,
                    selected_quantities=selected_qty_by_quant,
                    services=services,
                    backorder_items=backorder_items,
                )

                if result.get('success'):
                    return {
                        'success': False,
                        'needs_authorization': True,
                        'authorization_id': result['authorization_id'],
                        'authorization_name': result['authorization_name'],
                        'message': f'Solicitud {result["authorization_name"]} creada.',
                    }

        # ================================================================
        # NOTAS Y PRECIOS NORMALIZADOS
        # ================================================================
        full_notes = notes or ''
        normalized_prices = {}

        if product_prices and isinstance(product_prices, dict):
            normalized_prices = {str(k): float(v or 0.0) for k, v in product_prices.items()}

        fecha_orden = datetime.now()
        fecha_expiracion = self.env['stock.lot.hold.order']._get_default_fecha_expiracion(fecha_orden)

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

        success_count = 0
        error_count = 0
        failed_lots = []

        line_model = self.env['stock.lot.hold.order.line']

        # ================================================================
        # 1. LOTES FÍSICOS — AGRUPAR POR PRODUCTO
        # ================================================================
        if has_lots:
            product_quants = {}

            for quant_id in selected_lots:
                try:
                    quant = self.browse(int(quant_id))

                    if not quant.exists() or not quant.lot_id:
                        continue

                    if hasattr(quant, 'x_tiene_hold') and quant.x_tiene_hold:
                        error_count += 1
                        failed_lots.append({
                            'lot_name': quant.lot_id.name,
                            'error': 'Ya tiene apartado',
                        })
                        continue

                    selected_qty = selected_qty_by_quant.get(quant.id, quant.quantity or 0.0)
                    pid = quant.product_id.id

                    if pid not in product_quants:
                        product_quants[pid] = {
                            'product_id': pid,
                            'items': [],
                            'lot_ids': [],
                        }

                    product_quants[pid]['items'].append({
                        'quant': quant,
                        'quantity': selected_qty,
                    })
                    product_quants[pid]['lot_ids'].append(quant.lot_id.id)

                except Exception as e:
                    error_count += 1
                    failed_lots.append({
                        'lot_name': f'Quant {quant_id}',
                        'error': str(e),
                    })

            for pid, group in product_quants.items():
                try:
                    precio_unitario = float(normalized_prices.get(str(pid), 0.0))
                    cantidad_m2 = sum(item['quantity'] for item in group['items'])
                    first_quant = group['items'][0]['quant']

                    line_model.with_context(skip_hold_line_quantity_sync=True).create({
                        'order_id': order.id,
                        'product_id': pid,
                        'lot_ids': [(6, 0, group['lot_ids'])],
                        'lot_id': group['lot_ids'][0],
                        'quant_id': first_quant.id,
                        'cantidad_m2': cantidad_m2,
                        'precio_unitario': precio_unitario,
                        'x_price_selector': line_model._selector_from_price(
                            pid,
                            currency_code,
                            precio_unitario,
                        ),
                    })

                    success_count += len(group['lot_ids'])

                except Exception as e:
                    error_count += len(group['lot_ids'])
                    failed_lots.append({
                        'lot_name': f'Producto {pid}',
                        'error': str(e),
                    })

        # ================================================================
        # 2. BACKORDERS — SIN LOTE, SOLO CANTIDAD FINANCIERA
        # ================================================================
        if has_backorders:
            for item in backorder_items:
                try:
                    product_id = int(item['product_id'])
                    price_unit = float(item['price_unit'] or 0.0)

                    line_model.create({
                        'order_id': order.id,
                        'product_id': product_id,
                        'lot_id': False,
                        'quant_id': False,
                        'cantidad_m2': float(item['quantity'] or 0.0),
                        'precio_unitario': price_unit,
                        'x_price_selector': line_model._selector_from_price(
                            product_id,
                            currency_code,
                            price_unit,
                        ),
                    })

                except Exception as e:
                    error_count += 1
                    failed_lots.append({
                        'lot_name': f"Pedido ID {item.get('product_id')}",
                        'error': str(e),
                    })

        # ================================================================
        # 3. SERVICIOS
        # ================================================================
        if has_services:
            for service in services:
                try:
                    line_model.create({
                        'order_id': order.id,
                        'product_id': int(service['product_id']),
                        'lot_id': False,
                        'quant_id': False,
                        'cantidad_m2': float(service['quantity'] or 0.0),
                        'precio_unitario': float(service['price_unit'] or 0.0),
                        'x_price_selector': 'custom',
                    })

                except Exception as e:
                    error_count += 1
                    failed_lots.append({
                        'lot_name': f"Servicio ID {service.get('product_id')}",
                        'error': str(e),
                    })

        has_content = success_count > 0 or has_backorders or has_services

        if has_content:
            try:
                order.with_context(
                    skip_authorization_check=True,
                    skip_hold_line_quantity_sync=True,
                ).action_confirm()

            except Exception as e:
                return {
                    'success': 0,
                    'errors': 1,
                    'failed': [{'error': f'Error confirmando: {str(e)}'}],
                }
        else:
            if order:
                order.unlink()

        return {
            'success': success_count,
            'errors': error_count,
            'failed': failed_lots,
            'order_id': order.id if order else None,
            'order_name': order.name if order else None,
        }

    @api.model
    def create_price_authorization(
        self,
        operation_type,
        partner_id,
        project_id,
        selected_lots,
        currency_code,
        product_prices,
        product_groups,
        notes=None,
        architect_id=None,
        selected_quantities=None,
        services=None,
        backorder_items=None,
    ):
        """Crea solicitud de autorización de precio"""
        if isinstance(product_prices, dict):
            product_prices = {str(k): v for k, v in product_prices.items()}

        selected_quantities = selected_quantities or {}

        auth = self.env['price.authorization'].create({
            'seller_id': self.env.user.id,
            'operation_type': operation_type,
            'partner_id': partner_id,
            'project_id': project_id,
            'currency_code': currency_code,
            'notes': notes or '',
            'temp_data': {
                'selected_lots': selected_lots,
                'selected_quantities': {
                    str(k): float(v or 0.0)
                    for k, v in selected_quantities.items()
                },
                'product_prices': product_prices,
                'product_groups': product_groups,
                'architect_id': architect_id,
                'services': services or [],
                'backorder_items': backorder_items or [],
            },
        })

        Product = self.env['product.template']
        for product_id_key, group in product_groups.items():
            product_id = int(product_id_key)
            product = self.env['product.product'].browse(product_id)
            tmpl = product.product_tmpl_id

            requested_price = float(product_prices.get(str(product_id), 0.0))

            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': product_id,
                'quantity': group['total_quantity'],
                'lot_count': len(group['lots']),
                'requested_price': requested_price,
                'authorized_price': requested_price,
                'medium_price': Product._get_price_level_value(tmpl, 'medium', currency_code),
                'minimum_price': Product._get_price_level_value(tmpl, 'minimum', currency_code),
                'level_4_price': Product._get_price_level_value(tmpl, 'level_4', currency_code),
                'level_5_price': Product._get_price_level_value(tmpl, 'level_5', currency_code),
            })

        return {
            'success': True,
            'authorization_id': auth.id,
            'authorization_name': auth.name,
        }