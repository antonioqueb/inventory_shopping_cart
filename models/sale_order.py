# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    x_selected_lots = fields.Many2many('stock.quant', string='Lotes Seleccionados')

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, services=None, notes=None, pricelist_id=None, apply_tax=True, project_id=None, architect_id=None):
        if not partner_id or not products:
            raise UserError("Faltan parámetros: partner_id o products")
        
        if not pricelist_id:
            raise UserError("Debe especificar una lista de precios")
        
        # 🔑 OBTENER DIVISA DE LA LISTA DE PRECIOS
        pricelist = self.env['product.pricelist'].browse(pricelist_id)
        currency_code = pricelist.name  # 'USD' o 'MXN'
        
        # 🔑 VERIFICAR SI REQUIERE AUTORIZACIÓN
        product_prices = {}
        for product in products:
            product_prices[str(product['product_id'])] = product['price_unit']
        
        auth_check = self.env['product.template'].check_price_authorization_needed(
            product_prices, 
            currency_code
        )
        
        # ✅ SI REQUIERE AUTORIZACIÓN, CREARLA Y RETORNAR
        if auth_check['needs_authorization']:
            # Preparar datos de productos agrupados
            product_groups = {}
            for product in products:
                pid = product['product_id']
                if pid not in product_groups:
                    product_rec = self.env['product.product'].browse(pid)
                    product_groups[pid] = {
                        'name': product_rec.display_name,
                        'lots': [],
                        'total_quantity': 0
                    }
                
                # Agregar lotes
                for quant_id in product['selected_lots']:
                    quant = self.env['stock.quant'].browse(quant_id)
                    product_groups[pid]['lots'].append({
                        'id': quant_id,
                        'lot_name': quant.lot_id.name,
                        'quantity': quant.quantity
                    })
                    product_groups[pid]['total_quantity'] += quant.quantity
            
            # Crear autorización
            result = self.env['stock.quant'].create_price_authorization(
                operation_type='sale',
                partner_id=partner_id,
                project_id=project_id,
                selected_lots=[q_id for p in products for q_id in p['selected_lots']],
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
        
        # ✅ SI NO REQUIERE AUTORIZACIÓN, CREAR ORDEN NORMALMENTE
        company_id = self.env.context.get('company_id') or self.env.company.id
        
        # Verificar holds
        for product in products:
            for quant_id in product['selected_lots']:
                quant = self.env['stock.quant'].browse(quant_id)
                if quant.x_tiene_hold:
                    hold_partner = quant.x_hold_activo_id.partner_id
                    if hold_partner.id != partner_id:
                        raise UserError(f"El lote {quant.lot_id.name} está apartado para {hold_partner.name}")
        
        sale_order = self.with_company(company_id).create({
            'partner_id': partner_id,
            'note': notes or '',
            'pricelist_id': pricelist_id,
            'company_id': company_id,
        })
        
        # Crear líneas de productos
        for product in products:
            product_rec = self.env['product.product'].browse(product['product_id'])
            
            if apply_tax and product_rec.taxes_id:
                tax_ids = [(6, 0, product_rec.taxes_id.ids)]
            else:
                tax_ids = [(5, 0, 0)]
            
            self.env['sale.order.line'].with_company(company_id).create({
                'order_id': sale_order.id,
                'product_id': product['product_id'],
                'product_uom_qty': product['quantity'],
                'price_unit': product['price_unit'],
                'tax_ids': tax_ids,
                'x_selected_lots': [(6, 0, product['selected_lots'])],
                'company_id': company_id,
            })
        
        # Crear líneas de servicios
        if services:
            for service in services:
                service_product = self.env['product.product'].browse(service['product_id'])
                
                if apply_tax and service_product.taxes_id:
                    tax_ids = [(6, 0, service_product.taxes_id.ids)]
                else:
                    tax_ids = [(5, 0, 0)]
                
                self.env['sale.order.line'].with_company(company_id).create({
                    'order_id': sale_order.id,
                    'product_id': service['product_id'],
                    'product_uom_qty': service['quantity'],
                    'price_unit': service['price_unit'],
                    'tax_ids': tax_ids,
                    'company_id': company_id,
                })
        
        sale_order.with_company(company_id).action_confirm()
        
        # Asignar lotes específicos
        for line in sale_order.order_line:
            if line.x_selected_lots:
                picking = line.move_ids.mapped('picking_id')
                if picking:
                    self._assign_specific_lots(picking, line.product_id, line.x_selected_lots)
        
        # Limpiar carrito
        self.env['shopping.cart'].clear_cart()
        
        return {
            'success': True,
            'order_id': sale_order.id,
            'order_name': sale_order.name
        }
    
    def _assign_specific_lots(self, picking, product, quants):
        """
        Asigna lotes específicos al picking y copia las dimensiones
        del lote a la línea de movimiento para que aparezcan en la entrega.
        """
        for move in picking.move_ids.filtered(lambda m: m.product_id == product):
            move.move_line_ids.unlink()
            move_line_model = self.env['stock.move.line'].with_context(skip_hold_validation=True)
            
            for quant in quants:
                # Valores base para crear la línea de movimiento
                vals = {
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    'lot_id': quant.lot_id.id,
                    'location_id': quant.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'quantity': quant.quantity,
                    'product_uom_id': move.product_uom.id,
                }

                # === CORRECCIÓN: COPIAR DIMENSIONES DEL LOTE A LA LÍNEA ===
                # Esto es necesario porque al crear via código no se ejecuta el onchange
                # que normalmente llenaría estos campos 'temp'.
                if quant.lot_id:
                    vals.update({
                        'x_grosor_temp': quant.lot_id.x_grosor,
                        'x_alto_temp': quant.lot_id.x_alto,
                        'x_ancho_temp': quant.lot_id.x_ancho,
                        'x_bloque_temp': quant.lot_id.x_bloque,
                        'x_atado_temp': quant.lot_id.x_atado,
                        'x_tipo_temp': quant.lot_id.x_tipo,
                        'x_pedimento_temp': quant.lot_id.x_pedimento,
                        'x_contenedor_temp': quant.lot_id.x_contenedor,
                        'x_referencia_proveedor_temp': quant.lot_id.x_referencia_proveedor,
                    })
                    
                    # El campo x_grupo_temp es Many2many, requiere formato especial
                    if quant.lot_id.x_grupo:
                        vals['x_grupo_temp'] = [(6, 0, quant.lot_id.x_grupo.ids)]

                move_line_model.create(vals)