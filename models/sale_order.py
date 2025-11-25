# -*- coding: utf-8 -*-
# models/sale_order.py
from odoo import models, fields, api
from odoo.exceptions import UserError
from .utils.picking_cleaner import PickingLotCleaner
import logging

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    x_selected_lots = fields.Many2many('stock.quant', string='Lotes Seleccionados')

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    # Campos personalizados para Proyecto y Arquitecto
    x_project_id = fields.Many2one('project.project', string='Proyecto')
    x_architect_id = fields.Many2one('res.partner', string='Arquitecto')
    
    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, services=None, notes=None, pricelist_id=None, apply_tax=True, project_id=None, architect_id=None):
        """
        Crea una orden de venta desde el carrito de compras o desde una orden de reserva.
        Maneja autorización de precios, asignación de lotes y datos de proyecto/arquitecto.
        """
        if not partner_id or not products:
            raise UserError("Faltan parámetros: partner_id o products")
        
        if not pricelist_id:
            raise UserError("Debe especificar una lista de precios")
        
        pricelist = self.env['product.pricelist'].browse(pricelist_id)
        currency_code = pricelist.name
        
        # Si viene de hold order, omitir verificación de autorización
        # (Se asume que el hold ya fue autorizado o gestionado)
        from_hold_order = self.env.context.get('from_hold_order', False)
        
        if not from_hold_order:
            # === LOGICA DE AUTORIZACIÓN DE PRECIOS ===
            product_prices = {}
            for product in products:
                product_prices[str(product['product_id'])] = product['price_unit']
            
            auth_check = self.env['product.template'].check_price_authorization_needed(
                product_prices, 
                currency_code
            )
            
            if auth_check['needs_authorization']:
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
                    
                    # Recolectar lotes para la autorización
                    if 'selected_lots' in product:
                        for quant_id in product['selected_lots']:
                            quant = self.env['stock.quant'].browse(quant_id)
                            product_groups[pid]['lots'].append({
                                'id': quant_id,
                                'lot_name': quant.lot_id.name,
                                'quantity': quant.quantity
                            })
                            product_groups[pid]['total_quantity'] += quant.quantity
                
                # Crear solicitud de autorización
                result = self.env['stock.quant'].create_price_authorization(
                    operation_type='sale',
                    partner_id=partner_id,
                    project_id=project_id,
                    selected_lots=[q_id for p in products for q_id in p.get('selected_lots', [])],
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
        
        # === CREACIÓN DE LA ORDEN ===
        company_id = self.env.context.get('company_id') or self.env.company.id
        
        # Validación de Holds (Apartados)
        for product in products:
            if 'selected_lots' in product:
                for quant_id in product['selected_lots']:
                    quant = self.env['stock.quant'].browse(quant_id)
                    if quant.x_tiene_hold:
                        hold_partner = quant.x_hold_activo_id.partner_id
                        if hold_partner.id != partner_id:
                            raise UserError(f"El lote {quant.lot_id.name} está apartado para {hold_partner.name}")
        
        # Preparar valores para sale.order
        vals_order = {
            'partner_id': partner_id,
            'note': notes or '',
            'pricelist_id': pricelist_id,
            'company_id': company_id,
            # ✅ CORRECCIÓN: Asignar Proyecto y Arquitecto
            'x_project_id': project_id,
            'x_architect_id': architect_id,
        }

        sale_order = self.with_company(company_id).create(vals_order)
        
        # Crear líneas de productos físicos
        for product in products:
            product_rec = self.env['product.product'].browse(product['product_id'])
            
            if apply_tax and product_rec.taxes_id:
                tax_ids = [(6, 0, product_rec.taxes_id.ids)]
            else:
                tax_ids = [(5, 0, 0)]
            
            line_vals = {
                'order_id': sale_order.id,
                'product_id': product['product_id'],
                'product_uom_qty': product['quantity'],
                'price_unit': product['price_unit'],
                'tax_ids': tax_ids,
                'company_id': company_id,
            }
            
            # Asignar relación many2many de lotes si existen
            if 'selected_lots' in product and product['selected_lots']:
                line_vals['x_selected_lots'] = [(6, 0, product['selected_lots'])]

            self.env['sale.order.line'].with_company(company_id).create(line_vals)
        
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
        
        # Confirmar la orden (genera el picking)
        sale_order.with_company(company_id).action_confirm()
        
        # Asignar lotes específicos al picking generado
        for line in sale_order.order_line:
            if line.x_selected_lots:
                picking = line.move_ids.mapped('picking_id')
                if picking:
                    self._assign_specific_lots(picking, line.product_id, line.x_selected_lots)
        
        # Limpiar carrito solo si no viene de una orden de reserva (flujo normal de venta)
        if not from_hold_order:
            self.env['shopping.cart'].clear_cart()
        
        return {
            'success': True,
            'order_id': sale_order.id,
            'order_name': sale_order.name
        }
    
    def _assign_specific_lots(self, picking, product, quants):
        """
        Asigna lotes específicos al picking, reemplazando la reserva automática de Odoo.
        También copia las dimensiones del lote a la línea de movimiento para trazabilidad.
        """
        for move in picking.move_ids.filtered(lambda m: m.product_id == product):
            # Eliminar líneas reservadas automáticamente (FIFO/LIFO estándar)
            move.move_line_ids.unlink()
            
            move_line_model = self.env['stock.move.line'].with_context(skip_hold_validation=True)
            
            for quant in quants:
                # Preparar valores de creación
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

                # ✅ COPIAR DIMENSIONES DEL LOTE A LA LÍNEA DE MOVIMIENTO
                # Esto asegura que en el albarán de salida se vean las medidas correctas
                # ya que al crear por código no se disparan los onchanges de la interfaz.
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
                    
                    # Campo Many2many requiere sintaxis especial (6, 0, ids)
                    if quant.lot_id.x_grupo:
                        vals['x_grupo_temp'] = [(6, 0, quant.lot_id.x_grupo.ids)]

                move_line_model.create(vals)
    
    def action_confirm(self):
        _logger.info("Confirmando órdenes: %s", self.mapped('name'))
        
        all_partner_ids = self.mapped('partner_id.id')
        context = dict(self.env.context)
        if all_partner_ids:
            if len(all_partner_ids) == 1:
                context['allowed_partner_id'] = all_partner_ids[0]
            else:
                context['allowed_partner_ids'] = all_partner_ids
        
        res = super(SaleOrder, self.with_context(**context)).action_confirm()
        self._clear_auto_assigned_lots()
        return res
    
    def _clear_auto_assigned_lots(self):
        cleaner = PickingLotCleaner(self.env)
        for order in self:
            if order.picking_ids:
                cleaner.clear_pickings_lots(order.picking_ids)