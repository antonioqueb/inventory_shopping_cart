## ./__init__.py
```py
# -*- coding: utf-8 -*-
from . import models
```

## ./__manifest__.py
```py
# ./__manifest__.py
{
    'name': 'Carrito de Compra para Inventario Visual',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Sistema de carrito de compra y apartado múltiple desde inventario visual',
    'author': 'Alphaqueb Consulting SAS',
    'website': 'https://alphaqueb.com',
    'depends': ['stock', 'sale_stock', 'inventory_visual_enhanced', 'stock_lot_dimensions', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'inventory_shopping_cart/static/src/components/floating_bar/floating_bar.scss',
            'inventory_shopping_cart/static/src/components/dialogs/hold_wizard/hold_wizard.scss',
            'inventory_shopping_cart/static/src/components/dialogs/sale_order_wizard/sale_order_wizard.scss',
            
            'inventory_shopping_cart/static/src/components/cart_mixin/cart_mixin.js',
            'inventory_shopping_cart/static/src/components/floating_bar/floating_bar.js',
            'inventory_shopping_cart/static/src/components/dialogs/cart_dialog/cart_dialog.js',
            'inventory_shopping_cart/static/src/components/dialogs/hold_wizard/hold_wizard.js',
            'inventory_shopping_cart/static/src/components/dialogs/sale_order_wizard/sale_order_wizard.js',
            
            'inventory_shopping_cart/static/src/patches/inventory_controller_patch.xml',
            'inventory_shopping_cart/static/src/components/floating_bar/floating_bar.xml',
            'inventory_shopping_cart/static/src/components/dialogs/cart_dialog/cart_dialog.xml',
            'inventory_shopping_cart/static/src/components/dialogs/hold_wizard/hold_wizard.xml',
            'inventory_shopping_cart/static/src/components/dialogs/sale_order_wizard/sale_order_wizard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}```

## ./models/__init__.py
```py
# -*- coding: utf-8 -*-
from . import shopping_cart
from . import sale_order
from . import stock_quant
from . import product_template```

## ./models/product_template.py
```py
# ./models/product_template.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    x_price_usd_1 = fields.Float(string='Precio USD 1 (Alto)', digits='Product Price', default=0.0)
    x_price_usd_2 = fields.Float(string='Precio USD 2 (Medio)', digits='Product Price', default=0.0)
    x_price_usd_3 = fields.Float(string='Precio USD 3 (Bajo)', digits='Product Price', default=0.0)
    
    x_price_mxn_1 = fields.Float(string='Precio MXN 1 (Alto)', digits='Product Price', default=0.0)
    x_price_mxn_2 = fields.Float(string='Precio MXN 2 (Medio)', digits='Product Price', default=0.0)
    x_price_mxn_3 = fields.Float(string='Precio MXN 3 (Bajo)', digits='Product Price', default=0.0)
    
    @api.model
    def get_custom_prices(self, product_id, currency_code):
        product = self.browse(product_id)
        prices = []
        
        if currency_code == 'USD':
            if product.x_price_usd_1 > 0:
                prices.append({'label': 'Precio Alto', 'value': product.x_price_usd_1})
            if product.x_price_usd_2 > 0:
                prices.append({'label': 'Precio Medio', 'value': product.x_price_usd_2})
            if product.x_price_usd_3 > 0:
                prices.append({'label': 'Precio Bajo', 'value': product.x_price_usd_3})
        elif currency_code == 'MXN':
            if product.x_price_mxn_1 > 0:
                prices.append({'label': 'Precio Alto', 'value': product.x_price_mxn_1})
            if product.x_price_mxn_2 > 0:
                prices.append({'label': 'Precio Medio', 'value': product.x_price_mxn_2})
            if product.x_price_mxn_3 > 0:
                prices.append({'label': 'Precio Bajo', 'value': product.x_price_mxn_3})
        
        return prices```

## ./models/sale_order.py
```py
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    x_selected_lots = fields.Many2many('stock.quant', string='Lotes Seleccionados')

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, services=None, notes=None, pricelist_id=None, apply_tax=True):
        if not partner_id or not products:
            raise UserError("Faltan parámetros: partner_id o products")
        
        if not pricelist_id:
            raise UserError("Debe especificar una lista de precios")
        
        # 🔑 OBTENER COMPAÑÍA DEL CONTEXTO O USUARIO ACTUAL
        company_id = self.env.context.get('company_id') or self.env.company.id
        
        # Verificar holds
        for product in products:
            for quant_id in product['selected_lots']:
                quant = self.env['stock.quant'].browse(quant_id)
                if quant.x_tiene_hold:
                    hold_partner = quant.x_hold_activo_id.partner_id
                    if hold_partner.id != partner_id:
                        raise UserError(f"El lote {quant.lot_id.name} está apartado para {hold_partner.name}")
        
        # 🔑 CREAR ORDEN CON CONTEXTO DE COMPAÑÍA
        sale_order = self.with_company(company_id).create({
            'partner_id': partner_id,
            'note': notes or '',
            'pricelist_id': pricelist_id,
            'company_id': company_id,  # ✅ ASEGURAR company_id
        })
        
        # Crear líneas de productos CON CONTEXTO DE COMPAÑÍA
        for product in products:
            product_rec = self.env['product.product'].browse(product['product_id'])
            
            # ✅ Usar 'tax_ids' (plural)
            if apply_tax and product_rec.taxes_id:
                tax_ids = [(6, 0, product_rec.taxes_id.ids)]
            else:
                tax_ids = [(5, 0, 0)]  # Limpiar impuestos
            
            self.env['sale.order.line'].with_company(company_id).create({
                'order_id': sale_order.id,
                'product_id': product['product_id'],
                'product_uom_qty': product['quantity'],
                'price_unit': product['price_unit'],
                'tax_ids': tax_ids,
                'x_selected_lots': [(6, 0, product['selected_lots'])],
                'company_id': company_id,  # ✅ ASEGURAR company_id
            })
        
        # Crear líneas de servicios si existen
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
        
        # Confirmar orden CON CONTEXTO DE COMPAÑÍA
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
        for move in picking.move_ids.filtered(lambda m: m.product_id == product):
            move.move_line_ids.unlink()
            move_line_model = self.env['stock.move.line'].with_context(skip_hold_validation=True)
            
            for quant in quants:
                move_line_model.create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    'lot_id': quant.lot_id.id,
                    'location_id': quant.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'quantity': quant.quantity,
                    'product_uom_id': move.product_uom.id,
                })```

## ./models/shopping_cart.py
```py
# ./models/shopping_cart.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api

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
    
    _sql_constraints = [
        ('unique_user_quant', 'unique(user_id, quant_id)', 'Este lote ya está en tu carrito')
    ]
    
    @api.model
    def get_cart_items(self):
        """Obtener items del carrito del usuario actual"""
        items = self.search([('user_id', '=', self.env.user.id)])
        result = []
        for item in items:
            # ✅ CAMBIO: Usar 'stock.lot' en lugar de 'stock.production.lot'
            lot = self.env['stock.lot'].browse(item.lot_id)
            if not lot.exists():
                continue
                
            hold_info = ''
            seller_name = ''
            if item.quant_id.x_tiene_hold and item.quant_id.x_hold_activo_id:
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
                'tiene_hold': item.quant_id.x_tiene_hold,
                'hold_info': hold_info,
                'seller_name': seller_name
            })
        return result
    
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
        return {'success': True, 'removed': removed}```

## ./models/stock_quant.py
```py
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
        }```

## ./static/src/components/cart_mixin/cart_mixin.js
```js
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

const InventoryVisualController = registry.category("actions").get("inventory_visual_enhanced");

patch(InventoryVisualController.prototype, {
    setup() {
        super.setup();
        
        if (!this.state.activeProductId) {
            this.state.activeProductId = null;
            this.state.activeProductName = '';
        }
        
        this.cart = useState({
            items: [],
            totalQuantity: 0,
            totalLots: 0,
            productGroups: {}
        });
        
        this.isInCart = this.isInCart.bind(this);
        this.toggleCartSelection = this.toggleCartSelection.bind(this);
        this.selectAllCurrentProduct = this.selectAllCurrentProduct.bind(this);
        this.deselectAllCurrentProduct = this.deselectAllCurrentProduct.bind(this);
        this.areAllCurrentProductSelected = this.areAllCurrentProductSelected.bind(this);
        
        this.loadCartFromDB();
    },
    
    async loadCartFromDB() {
        try {
            const items = await this.orm.call('shopping.cart', 'get_cart_items', []);
            this.cart.items = items;
            this.updateCartSummary();
        } catch (error) {
            console.error('[CART] Error cargando carrito:', error);
        }
    },
    
    async syncCartToDB() {
        try {
            await this.orm.call('stock.quant', 'sync_cart_to_session', [this.cart.items]);
        } catch (error) {
            console.error('[CART] Error sincronizando carrito:', error);
        }
    },
    
    async toggleProduct(productId, quantIds) {
        const isExpanded = this.state.expandedProducts.has(productId);

        this.state.activeProductId = productId;
        const product = this.state.products.find(p => p.product_id === productId);
        this.state.activeProductName = product ? product.product_name : '';

        if (isExpanded) {
            this.state.expandedProducts.delete(productId);
        } else {
            this.state.expandedProducts.add(productId);

            if (!this.state.productDetails[productId]) {
                await this.loadProductDetails(productId, quantIds);
            }
        }

        this.state.expandedProducts = new Set(this.state.expandedProducts);
    },
    
    isInCart(detailId) {
        return this.cart.items.some(item => item.id === detailId);
    },
    
    async toggleCartSelection(detail) {
        const index = this.cart.items.findIndex(item => item.id === detail.id);
        
        if (index >= 0) {
            this.cart.items.splice(index, 1);
            await this.orm.call('shopping.cart', 'remove_from_cart', [detail.id]);
        } else {
            const newItem = {
                id: detail.id,
                lot_id: detail.lot_id,
                lot_name: detail.lot_name,
                product_id: this.getCurrentProductId(detail),
                product_name: this.getCurrentProductName(detail),
                quantity: detail.quantity,
                location_name: detail.location_name,
                tiene_hold: detail.tiene_hold,
                hold_info: detail.hold_info,
                seller_name: detail.seller_name || ''
            };
            this.cart.items.push(newItem);
            
            try {
                await this.orm.call('shopping.cart', 'add_to_cart', [], {
                    quant_id: newItem.id,
                    lot_id: newItem.lot_id,
                    product_id: newItem.product_id,
                    quantity: newItem.quantity,
                    location_name: newItem.location_name
                });
            } catch (error) {
                console.error('[CART] Error agregando al carrito:', error);
                this.cart.items.pop();
                this.notification.add("Error al agregar al carrito", { type: "danger" });
            }
        }
        
        this.updateCartSummary();
        
        // ✅ FORZAR ACTUALIZACIÓN REACTIVA explícita
        this.cart.items = [...this.cart.items];
    },
    
    async selectAllCurrentProduct() {
        if (!this.state.activeProductId) return;
        
        const details = this.getProductDetails(this.state.activeProductId);
        
        for (const detail of details) {
            if (!this.isInCart(detail.id)) {
                await this.toggleCartSelection(detail);
            }
        }
        
        // ✅ Forzar actualización final
        this.cart.items = [...this.cart.items];
    },
    
    async deselectAllCurrentProduct() {
        if (!this.state.activeProductId) return;
        
        const details = this.getProductDetails(this.state.activeProductId);
        
        for (const detail of details) {
            if (this.isInCart(detail.id)) {
                await this.toggleCartSelection(detail);
            }
        }
        
        // ✅ Forzar actualización final
        this.cart.items = [...this.cart.items];
    },
    
    areAllCurrentProductSelected() {
        if (!this.state.activeProductId) return false;
        
        const details = this.getProductDetails(this.state.activeProductId);
        if (details.length === 0) return false;
        
        return details.every(detail => this.isInCart(detail.id));
    },
    
    getCurrentProductId(detail) {
        for (const product of this.state.products) {
            const details = this.getProductDetails(product.product_id);
            if (details.find(d => d.id === detail.id)) {
                return product.product_id;
            }
        }
        return null;
    },
    
    getCurrentProductName(detail) {
        for (const product of this.state.products) {
            const details = this.getProductDetails(product.product_id);
            if (details.find(d => d.id === detail.id)) {
                return product.product_name;
            }
        }
        return '';
    },
    
    updateCartSummary() {
        this.cart.totalLots = this.cart.items.length;
        this.cart.totalQuantity = this.cart.items.reduce((sum, item) => sum + item.quantity, 0);
        
        const groups = {};
        for (const item of this.cart.items) {
            if (!groups[item.product_id]) {
                groups[item.product_id] = {
                    name: item.product_name,
                    lots: [],
                    total_quantity: 0
                };
            }
            groups[item.product_id].lots.push(item);
            groups[item.product_id].total_quantity += item.quantity;
        }
        this.cart.productGroups = groups;
    },
    
    async clearCart() {
        this.cart.items = [];
        this.updateCartSummary();
        await this.orm.call('shopping.cart', 'clear_cart', []);
        
        // ✅ OBTENER TODOS LOS PRODUCTOS QUE ESTÁN EXPANDIDOS
        const expandedProductIds = Array.from(this.state.expandedProducts);
        
        if (expandedProductIds.length > 0) {
            // ✅ COLAPSAR TODOS LOS PRODUCTOS EXPANDIDOS
            this.state.expandedProducts.clear();
            this.state.expandedProducts = new Set(this.state.expandedProducts);
            
            // Pequeño delay para que el DOM se actualice
            await new Promise(resolve => setTimeout(resolve, 50));
            
            // ✅ RE-EXPANDIR TODOS LOS PRODUCTOS QUE ESTABAN EXPANDIDOS
            for (const productId of expandedProductIds) {
                const product = this.state.products.find(p => p.product_id === productId);
                if (product) {
                    this.state.expandedProducts.add(productId);
                    await this.loadProductDetails(productId, product.quant_ids);
                }
            }
            
            this.state.expandedProducts = new Set(this.state.expandedProducts);
        }
    },
    
    async removeLotsWithHold() {
        const before = this.cart.items.length;
        this.cart.items = this.cart.items.filter(item => !item.tiene_hold);
        const after = this.cart.items.length;
        this.updateCartSummary();
        
        await this.orm.call('shopping.cart', 'remove_holds_from_cart', []);
        
        // ✅ Forzar actualización reactiva
        this.cart.items = [...this.cart.items];
        
        this.notification.add("Lotes apartados eliminados del carrito", { type: "success" });
        
        // ✅ OBTENER TODOS LOS PRODUCTOS QUE ESTÁN EXPANDIDOS
        const expandedProductIds = Array.from(this.state.expandedProducts);
        
        if (expandedProductIds.length > 0) {
            // ✅ COLAPSAR TODOS LOS PRODUCTOS EXPANDIDOS
            this.state.expandedProducts.clear();
            this.state.expandedProducts = new Set(this.state.expandedProducts);
            
            await new Promise(resolve => setTimeout(resolve, 50));
            
            // ✅ RE-EXPANDIR TODOS LOS PRODUCTOS QUE ESTABAN EXPANDIDOS
            for (const productId of expandedProductIds) {
                const product = this.state.products.find(p => p.product_id === productId);
                if (product) {
                    this.state.expandedProducts.add(productId);
                    await this.loadProductDetails(productId, product.quant_ids);
                }
            }
            
            this.state.expandedProducts = new Set(this.state.expandedProducts);
        }
    },
    
    formatNumber(num) {
        if (num === null || num === undefined) return "0";
        return new Intl.NumberFormat('es-MX', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(num);
    }
});```

## ./static/src/components/dialogs/cart_dialog/cart_dialog.js
```js
/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class CartDialog extends Component {
    setup() {
        this.cart = this.props.cart;
    }
    
    get hasHolds() {
        return this.cart.items.some(item => item.tiene_hold);
    }
    
    removeHolds() {
        this.props.onRemoveHolds();
        if (this.cart.totalLots === 0) {
            this.props.close();
        }
    }
    
    createHolds() {
        this.props.close();
        this.props.onCreateHolds();
    }
    
    createSaleOrder() {
        this.props.close();
        this.props.onCreateSaleOrder();
    }
    
    formatNumber(num) {
        return new Intl.NumberFormat('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num);
    }
}

CartDialog.template = "inventory_shopping_cart.CartDialog";
CartDialog.components = { Dialog };
CartDialog.props = {
    close: Function,
    cart: Object,
    onRemoveHolds: Function,
    onCreateHolds: Function,
    onCreateSaleOrder: Function,
};
```

## ./static/src/components/dialogs/cart_dialog/cart_dialog.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    
    <t t-name="inventory_shopping_cart.CartDialog" owl="1">
        <Dialog size="'xl'" title="'🛒 Carrito de Compra'">
            <div class="cart-dialog-content">
                <div class="alert alert-warning" t-if="hasHolds">
                    <i class="fa fa-exclamation-triangle me-2"></i>
                    <strong>Advertencia:</strong> Hay lotes apartados que no podrán venderse
                </div>

                <t t-foreach="Object.entries(cart.productGroups)" t-as="entry" t-key="entry[0]">
                    <t t-set="productId" t-value="entry[0]"/>
                    <t t-set="group" t-value="entry[1]"/>
                    
                    <div class="product-group mb-4">
                        <div class="product-header">
                            <h5><i class="fa fa-cube me-2"></i><t t-esc="group.name"/></h5>
                            <span class="badge bg-secondary"><t t-esc="formatNumber(group.total_quantity)"/> m²</span>
                        </div>
                        
                        <table class="table table-sm">
                            <tbody>
                                <t t-foreach="group.lots" t-as="lot" t-key="lot.id">
                                    <tr>
                                        <td><t t-esc="lot.lot_name"/></td>
                                        <td><t t-esc="formatNumber(lot.quantity)"/> m²</td>
                                        <td><t t-esc="lot.location_name"/></td>
                                        <td>
                                            <span t-if="lot.tiene_hold" class="badge bg-warning">
                                                🔒 <t t-esc="lot.seller_name || 'Apartado'"/>
                                            </span>
                                        </td>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                    </div>
                </t>

                <div class="cart-summary-footer">
                    <h4>Total: <t t-esc="formatNumber(cart.totalQuantity)"/> m²</h4>
                    <p><t t-esc="cart.totalLots"/> lotes en <t t-esc="Object.keys(cart.productGroups).length"/> productos</p>
                </div>
            </div>

            <t t-set-slot="footer">
                <button class="btn btn-warning" t-if="hasHolds" t-on-click="removeHolds">
                    <i class="fa fa-times"></i> Eliminar Apartados
                </button>
                <button class="btn btn-info" t-on-click="createHolds">
                    <i class="fa fa-lock"></i> Apartar Todo
                </button>
                <button class="btn btn-primary" t-on-click="createSaleOrder">
                    <i class="fa fa-file-text"></i> Crear Orden de Venta
                </button>
            </t>
        </Dialog>
    </t>
    
</templates>```

## ./static/src/components/dialogs/hold_wizard/hold_wizard.js
```js
/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class HoldWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        
        this.productIds = Object.keys(this.props.productGroups).map(id => parseInt(id));
        this.currentProductIndex = 0;
        
        this.state = useState({
            // Cliente
            searchPartnerTerm: '',
            partners: [],
            selectedPartnerId: null,
            selectedPartnerName: '',
            showCreatePartner: false,
            newPartnerName: '',
            newPartnerVat: '',
            newPartnerRef: '',
            
            // Proyecto
            searchProjectTerm: '',
            projects: [],
            selectedProjectId: null,
            selectedProjectName: '',
            showCreateProject: false,
            newProjectName: '',
            
            // Arquitecto
            searchArchitectTerm: '',
            architects: [],
            selectedArchitectId: null,
            selectedArchitectName: '',
            showCreateArchitect: false,
            newArchitectName: '',
            newArchitectVat: '',
            newArchitectRef: '',
            
            // Precios
            selectedCurrency: 'USD',
            pricelists: [],
            selectedPricelistId: null,
            productPrices: {},
            productPriceOptions: {},
            
            // Notas
            notas: '',
            
            // Vendedor
            sellerName: '',
            sellerId: null,
            
            // UI
            isCreating: false,
            currentStep: 1,
        });
        
        this.searchTimeout = null;
        this.loadCurrentUser();
        this.loadPricelists();
    }
    
    async loadCurrentUser() {
        try {
            const result = await this.orm.call(
                'stock.quant',
                'get_current_user_info',
                []
            );
            this.state.sellerName = result.name;
            this.state.sellerId = result.id;
        } catch (error) {
            console.error("Error obteniendo usuario actual:", error);
            this.state.sellerName = 'Usuario Actual';
        }
    }
    
    async loadPricelists() {
        try {
            const pricelists = await this.orm.searchRead(
                "product.pricelist",
                [['name', 'in', ['USD', 'MXN']]],
                ['id', 'name', 'currency_id']
            );
            this.state.pricelists = pricelists;
            
            const usd = pricelists.find(p => p.name === 'USD');
            if (usd) {
                this.state.selectedPricelistId = usd.id;
                this.state.selectedCurrency = 'USD';
            }
            
            await this.loadAllProductPrices();
        } catch (error) {
            console.error("Error cargando listas de precios:", error);
            this.notification.add("Error al cargar listas de precios", { type: "warning" });
        }
    }
    
    async loadAllProductPrices() {
        for (const productId of this.productIds) {
            try {
                const prices = await this.orm.call(
                    "product.template",
                    "get_custom_prices",
                    [],
                    {
                        product_id: productId,
                        currency_code: this.state.selectedCurrency
                    }
                );
                
                this.state.productPriceOptions[productId] = prices;
                
                if (prices.length > 0 && !this.state.productPrices[productId]) {
                    this.state.productPrices[productId] = prices[0].value;
                }
            } catch (error) {
                console.error(`Error cargando precios para producto ${productId}:`, error);
            }
        }
    }
    
    async onCurrencyChange(ev) {
        const pricelistName = ev.target.value;
        this.state.selectedCurrency = pricelistName;
        
        const pricelist = this.state.pricelists.find(p => p.name === pricelistName);
        if (pricelist) {
            this.state.selectedPricelistId = pricelist.id;
        }
        
        await this.loadAllProductPrices();
    }
    
    onPriceChange(productId, value) {
        const numValue = parseFloat(value);
        const options = this.state.productPriceOptions[productId] || [];
        
        if (options.length === 0) {
            this.state.productPrices[productId] = numValue;
            return;
        }
        
        const minPrice = Math.min(...options.map(opt => opt.value));
        
        if (numValue < minPrice) {
            this.notification.add(
                `El precio no puede ser menor a ${this.formatNumber(minPrice)}`,
                { type: "warning" }
            );
            this.state.productPrices[productId] = minPrice;
        } else {
            this.state.productPrices[productId] = numValue;
        }
    }
    
    // ========== CLIENTE ==========
    
    onSearchPartner(ev) {
        const value = ev.target.value;
        this.state.searchPartnerTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchPartners();
        }, 300);
    }
    
    async searchPartners() {
        try {
            const partners = await this.orm.call(
                "stock.quant",
                "search_partners",
                [],
                { name: this.state.searchPartnerTerm.trim() }
            );
            
            this.state.partners = partners;
        } catch (error) {
            console.error("Error buscando clientes:", error);
            this.notification.add("Error al buscar clientes", { type: "danger" });
        }
    }
    
    selectPartner(partner) {
        this.state.selectedPartnerId = partner.id;
        this.state.selectedPartnerName = partner.display_name;
        this.state.showCreatePartner = false;
    }
    
    toggleCreatePartner() {
        this.state.showCreatePartner = !this.state.showCreatePartner;
        if (this.state.showCreatePartner) {
            this.state.selectedPartnerId = null;
            this.state.selectedPartnerName = '';
        }
    }
    
    async createPartner() {
        if (!this.state.newPartnerName.trim()) {
            this.notification.add("El nombre del cliente es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_partner",
                [],
                {
                    name: this.state.newPartnerName.trim(),
                    vat: this.state.newPartnerVat.trim(),
                    ref: this.state.newPartnerRef.trim()
                }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectPartner(result.partner);
                this.notification.add(`Cliente "${result.partner.name}" creado exitosamente`, { type: "success" });
                this.state.newPartnerName = '';
                this.state.newPartnerVat = '';
                this.state.newPartnerRef = '';
            }
        } catch (error) {
            console.error("Error creando cliente:", error);
            this.notification.add("Error al crear cliente", { type: "danger" });
        }
    }
    
    // ========== PROYECTO ==========
    
    onSearchProject(ev) {
        const value = ev.target.value;
        this.state.searchProjectTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchProjects();
        }, 300);
    }
    
    async searchProjects() {
        try {
            const projects = await this.orm.call(
                "stock.quant",
                "get_projects",
                [],
                { search_term: this.state.searchProjectTerm.trim() }
            );
            
            this.state.projects = projects;
        } catch (error) {
            console.error("Error buscando proyectos:", error);
            this.notification.add("Error al buscar proyectos", { type: "danger" });
        }
    }
    
    selectProject(project) {
        this.state.selectedProjectId = project.id;
        this.state.selectedProjectName = project.name;
        this.state.showCreateProject = false;
    }
    
    toggleCreateProject() {
        this.state.showCreateProject = !this.state.showCreateProject;
        if (this.state.showCreateProject) {
            this.state.selectedProjectId = null;
            this.state.selectedProjectName = '';
        }
    }
    
    async createProject() {
        if (!this.state.newProjectName.trim()) {
            this.notification.add("El nombre del proyecto es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_project",
                [],
                { name: this.state.newProjectName.trim() }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectProject(result.project);
                this.notification.add(`Proyecto "${result.project.name}" creado exitosamente`, { type: "success" });
                this.state.newProjectName = '';
            }
        } catch (error) {
            console.error("Error creando proyecto:", error);
            this.notification.add("Error al crear proyecto", { type: "danger" });
        }
    }
    
    // ========== ARQUITECTO ==========
    
    onSearchArchitect(ev) {
        const value = ev.target.value;
        this.state.searchArchitectTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchArchitects();
        }, 300);
    }
    
    async searchArchitects() {
        try {
            const architects = await this.orm.call(
                "stock.quant",
                "get_architects",
                [],
                { search_term: this.state.searchArchitectTerm.trim() }
            );
            
            this.state.architects = architects;
        } catch (error) {
            console.error("Error buscando arquitectos:", error);
            this.notification.add("Error al buscar arquitectos", { type: "danger" });
        }
    }
    
    selectArchitect(architect) {
        this.state.selectedArchitectId = architect.id;
        this.state.selectedArchitectName = architect.display_name;
        this.state.showCreateArchitect = false;
    }
    
    toggleCreateArchitect() {
        this.state.showCreateArchitect = !this.state.showCreateArchitect;
        if (this.state.showCreateArchitect) {
            this.state.selectedArchitectId = null;
            this.state.selectedArchitectName = '';
        }
    }
    
    async createArchitect() {
        if (!this.state.newArchitectName.trim()) {
            this.notification.add("El nombre del arquitecto es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_architect",
                [],
                {
                    name: this.state.newArchitectName.trim(),
                    vat: this.state.newArchitectVat.trim(),
                    ref: this.state.newArchitectRef.trim()
                }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectArchitect(result.architect);
                this.notification.add(`Arquitecto "${result.architect.name}" creado exitosamente`, { type: "success" });
                this.state.newArchitectName = '';
                this.state.newArchitectVat = '';
                this.state.newArchitectRef = '';
            }
        } catch (error) {
            console.error("Error creando arquitecto:", error);
            this.notification.add("Error al crear arquitecto", { type: "danger" });
        }
    }
    
    // ========== NAVEGACIÓN ==========
    
    nextStep() {
        if (this.state.currentStep === 1 && !this.state.selectedPartnerId) {
            this.notification.add("Debe seleccionar o crear un cliente", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 2 && !this.state.selectedProjectId) {
            this.notification.add("Debe seleccionar o crear un proyecto", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 3 && !this.state.selectedArchitectId) {
            this.notification.add("Debe seleccionar o crear un arquitecto", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 4) {
            // Validar precios
            const hasInvalidPrice = this.productIds.some(pid => {
                const price = this.state.productPrices[pid];
                return !price || price <= 0;
            });
            
            if (hasInvalidPrice) {
                this.notification.add("Debe configurar precios para todos los productos", { type: "warning" });
                return;
            }
        }
        
        if (this.state.currentStep < 5) {
            this.state.currentStep++;
        }
    }
    
    prevStep() {
        if (this.state.currentStep > 1) {
            this.state.currentStep--;
        }
    }
    
    // ========== CREAR HOLDS ==========
    
    async createHolds() {
        if (!this.state.selectedPartnerId || !this.state.selectedProjectId || !this.state.selectedArchitectId) {
            this.notification.add("Faltan datos requeridos", { type: "warning" });
            return;
        }
        
        this.state.isCreating = true;
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_holds_from_cart",
                [],
                {
                    partner_id: this.state.selectedPartnerId,
                    project_id: this.state.selectedProjectId,
                    architect_id: this.state.selectedArchitectId,
                    selected_lots: this.props.selectedLots,
                    notes: this.state.notas,
                    currency_code: this.state.selectedCurrency,
                    product_prices: this.state.productPrices
                }
            );
            
            if (result.success > 0) {
                this.notification.add(
                    `${result.success} lotes apartados correctamente`, 
                    { type: "success" }
                );
                this.props.onSuccess();
                this.props.close();
            }
            
            if (result.errors > 0) {
                let msg = `${result.errors} lotes no pudieron apartarse:\n`;
                result.failed.forEach(f => { 
                    msg += `\n• ${f.lot_name || 'Lote'}: ${f.error}`; 
                });
                this.notification.add(msg, { type: "warning", sticky: true });
            }
        } catch (error) {
            console.error("Error creando apartados:", error);
            this.notification.add("Error al crear apartados", { type: "danger" });
        } finally {
            this.state.isCreating = false;
        }
    }
    
    formatNumber(num) {
        return new Intl.NumberFormat('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num);
    }
}

HoldWizard.template = "inventory_shopping_cart.HoldWizard";
HoldWizard.components = { Dialog };
HoldWizard.props = {
    close: Function,
    selectedLots: Array,
    productGroups: Object,
    onSuccess: Function,
};```

## ./static/src/components/dialogs/hold_wizard/hold_wizard.scss
```scss
.hold-wizard-content {
  .steps-indicator {
    padding: 16px 0;
    
    .step-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      flex: 1;
      
      .step-number {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: #E0E0E0;
        color: #808080;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 14px;
        transition: all 0.3s ease;
      }
      
      .step-label {
        font-size: 12px;
        color: #808080;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        transition: all 0.3s ease;
      }
      
      &.active {
        .step-number {
          background: #714B67;
          color: white;
        }
        
        .step-label {
          color: #714B67;
        }
      }
      
      &.completed {
        .step-number {
          background: #21B799;
          color: white;
        }
        
        .step-label {
          color: #21B799;
        }
      }
    }
    
    .step-line {
      flex: 1;
      height: 2px;
      background: #E0E0E0;
      margin: 0 8px;
      align-self: center;
      transition: all 0.3s ease;
      margin-top: -24px;
      
      &.active {
        background: #714B67;
      }
    }
  }
  
  .step-content {
    min-height: 400px;
    animation: fadeIn 0.3s ease-in;
  }
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}```

## ./static/src/components/dialogs/hold_wizard/hold_wizard.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    
    <t t-name="inventory_shopping_cart.HoldWizard" owl="1">
        <Dialog size="'lg'">
            <div class="hold-wizard-content">
                <!-- Header con total de lotes -->
                <div class="alert alert-light border-start border-4 border-secondary mb-4">
                    <div class="d-flex align-items-center">
                        <i class="fa fa-lock fa-2x text-secondary me-3"></i>
                        <div>
                            <h5 class="mb-1 fw-bold">Apartado Múltiple</h5>
                            <small class="text-muted">
                                <i class="fa fa-cubes me-1"></i>
                                <strong t-esc="props.selectedLots.length"></strong> lotes seleccionados
                            </small>
                        </div>
                    </div>
                </div>
                
                <!-- Indicador de pasos -->
                <div class="steps-indicator mb-4">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 1, completed: state.currentStep > 1 }">
                            <div class="step-number">1</div>
                            <div class="step-label">Cliente</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 1 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 2, completed: state.currentStep > 2 }">
                            <div class="step-number">2</div>
                            <div class="step-label">Proyecto</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 2 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 3, completed: state.currentStep > 3 }">
                            <div class="step-number">3</div>
                            <div class="step-label">Arquitecto</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 3 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 4, completed: state.currentStep > 4 }">
                            <div class="step-number">4</div>
                            <div class="step-label">Precios</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 4 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 5 }">
                            <div class="step-number">5</div>
                            <div class="step-label">Confirmar</div>
                        </div>
                    </div>
                </div>
                
                <!-- PASO 1: CLIENTE -->
                <div class="step-content" t-if="state.currentStep === 1">
                    <h5 class="mb-3">
                        <i class="fa fa-user text-secondary me-2"></i>
                        Seleccionar Cliente
                    </h5>
                    
                    <div class="btn-group w-100 mb-3" role="group">
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="!state.showCreatePartner ? 'btn-secondary' : 'btn-outline-secondary'"
                            t-on-click="() => this.state.showCreatePartner = false"
                        >
                            <i class="fa fa-search me-2"></i>
                            Buscar Existente
                        </button>
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="state.showCreatePartner ? 'btn-secondary' : 'btn-outline-secondary'"
                            t-on-click="toggleCreatePartner"
                        >
                            <i class="fa fa-plus me-2"></i>
                            Crear Nuevo
                        </button>
                    </div>
                    
                    <t t-if="!state.showCreatePartner">
                        <div class="input-group mb-2">
                            <span class="input-group-text">
                                <i class="fa fa-search"></i>
                            </span>
                            <input 
                                type="text"
                                class="form-control"
                                placeholder="Buscar por nombre, RFC o referencia..."
                                t-model="state.searchPartnerTerm"
                                t-on-input="onSearchPartner"
                            />
                        </div>
                        
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedPartnerName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Cliente seleccionado:</strong><br/>
                                <t t-esc="state.selectedPartnerName"/>
                            </div>
                        </div>
                        
                        <div class="list-group" style="max-height: 300px; overflow-y: auto;" t-if="state.partners.length > 0 and !state.selectedPartnerName">
                            <t t-foreach="state.partners" t-as="partner" t-key="partner.id">
                                <button 
                                    type="button"
                                    class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                    t-on-click="() => this.selectPartner(partner)"
                                >
                                    <div>
                                        <strong t-esc="partner.name"></strong>
                                        <small class="text-muted ms-2" t-if="partner.ref">
                                            [<t t-esc="partner.ref"/>]
                                        </small>
                                        <small class="text-muted ms-2" t-if="partner.vat">
                                            RFC: <t t-esc="partner.vat"/>
                                        </small>
                                    </div>
                                    <i class="fa fa-chevron-right text-muted"></i>
                                </button>
                            </t>
                        </div>
                    </t>
                    
                    <t t-if="state.showCreatePartner">
                        <div class="card bg-light border mb-3">
                            <div class="card-body">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">
                                        Nombre del Cliente <span class="text-danger">*</span>
                                    </label>
                                    <input 
                                        type="text"
                                        class="form-control"
                                        placeholder="Nombre completo o razón social..."
                                        t-model="state.newPartnerName"
                                    />
                                </div>
                                <div class="row">
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">RFC (opcional)</label>
                                        <input 
                                            type="text"
                                            class="form-control"
                                            placeholder="RFC..."
                                            t-model="state.newPartnerVat"
                                        />
                                    </div>
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">Referencia (opcional)</label>
                                        <input 
                                            type="text"
                                            class="form-control"
                                            placeholder="Código de referencia..."
                                            t-model="state.newPartnerRef"
                                        />
                                    </div>
                                </div>
                                <button 
                                    class="btn btn-secondary w-100"
                                    t-on-click="createPartner"
                                >
                                    <i class="fa fa-plus-circle me-2"></i>
                                    Crear Cliente
                                </button>
                            </div>
                        </div>
                    </t>
                </div>
                
                <!-- PASO 2: PROYECTO -->
                <div class="step-content" t-if="state.currentStep === 2">
                    <h5 class="mb-3">
                        <i class="fa fa-folder text-secondary me-2"></i>
                        Seleccionar Proyecto
                    </h5>
                    
                    <div class="btn-group w-100 mb-3" role="group">
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="!state.showCreateProject ? 'btn-secondary' : 'btn-outline-secondary'"
                            t-on-click="() => this.state.showCreateProject = false"
                        >
                            <i class="fa fa-search me-2"></i>
                            Buscar Existente
                        </button>
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="state.showCreateProject ? 'btn-secondary' : 'btn-outline-secondary'"
                            t-on-click="toggleCreateProject"
                        >
                            <i class="fa fa-plus me-2"></i>
                            Crear Nuevo
                        </button>
                    </div>
                    
                    <t t-if="!state.showCreateProject">
                        <div class="input-group mb-2">
                            <span class="input-group-text">
                                <i class="fa fa-search"></i>
                            </span>
                            <input 
                                type="text"
                                class="form-control"
                                placeholder="Buscar proyecto..."
                                t-model="state.searchProjectTerm"
                                t-on-input="onSearchProject"
                            />
                        </div>
                        
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedProjectName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Proyecto seleccionado:</strong><br/>
                                <t t-esc="state.selectedProjectName"/>
                            </div>
                        </div>
                        
                        <div class="list-group" style="max-height: 300px; overflow-y: auto;" t-if="state.projects.length > 0 and !state.selectedProjectName">
                            <t t-foreach="state.projects" t-as="project" t-key="project.id">
                                <button 
                                    type="button"
                                    class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                    t-on-click="() => this.selectProject(project)"
                                >
                                    <div>
                                        <strong t-esc="project.name"></strong>
                                    </div>
                                    <i class="fa fa-chevron-right text-muted"></i>
                                </button>
                            </t>
                        </div>
                    </t>
                    
                    <t t-if="state.showCreateProject">
                        <div class="card bg-light border mb-3">
                            <div class="card-body">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">
                                        Nombre del Proyecto <span class="text-danger">*</span>
                                    </label>
                                    <input 
                                        type="text"
                                        class="form-control"
                                        placeholder="Nombre del proyecto..."
                                        t-model="state.newProjectName"
                                    />
                                </div>
                                <button 
                                    class="btn btn-secondary w-100"
                                    t-on-click="createProject"
                                >
                                    <i class="fa fa-plus-circle me-2"></i>
                                    Crear Proyecto
                                </button>
                            </div>
                        </div>
                    </t>
                </div>
                
                <!-- PASO 3: ARQUITECTO -->
                <div class="step-content" t-if="state.currentStep === 3">
                    <h5 class="mb-3">
                        <i class="fa fa-user-circle text-secondary me-2"></i>
                        Seleccionar Arquitecto
                    </h5>
                    
                    <div class="btn-group w-100 mb-3" role="group">
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="!state.showCreateArchitect ? 'btn-secondary' : 'btn-outline-secondary'"
                            t-on-click="() => this.state.showCreateArchitect = false"
                        >
                            <i class="fa fa-search me-2"></i>
                            Buscar Existente
                        </button>
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="state.showCreateArchitect ? 'btn-secondary' : 'btn-outline-secondary'"
                            t-on-click="toggleCreateArchitect"
                        >
                            <i class="fa fa-plus me-2"></i>
                            Crear Nuevo
                        </button>
                    </div>
                    
                    <t t-if="!state.showCreateArchitect">
                        <div class="input-group mb-2">
                            <span class="input-group-text">
                                <i class="fa fa-search"></i>
                            </span>
                            <input 
                                type="text"
                                class="form-control"
                                placeholder="Buscar arquitecto..."
                                t-model="state.searchArchitectTerm"
                                t-on-input="onSearchArchitect"
                            />
                        </div>
                        
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedArchitectName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Arquitecto seleccionado:</strong><br/>
                                <t t-esc="state.selectedArchitectName"/>
                            </div>
                        </div>
                        
                        <div class="list-group" style="max-height: 300px; overflow-y: auto;" t-if="state.architects.length > 0 and !state.selectedArchitectName">
                            <t t-foreach="state.architects" t-as="architect" t-key="architect.id">
                                <button 
                                    type="button"
                                    class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                    t-on-click="() => this.selectArchitect(architect)"
                                >
                                    <div>
                                        <strong t-esc="architect.name"></strong>
                                        <small class="text-muted ms-2" t-if="architect.ref">
                                            [<t t-esc="architect.ref"/>]
                                        </small>
                                        <small class="text-muted ms-2" t-if="architect.vat">
                                            RFC: <t t-esc="architect.vat"/>
                                        </small>
                                    </div>
                                    <i class="fa fa-chevron-right text-muted"></i>
                                </button>
                            </t>
                        </div>
                    </t>
                    
                    <t t-if="state.showCreateArchitect">
                        <div class="card bg-light border mb-3">
                            <div class="card-body">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">
                                        Nombre del Arquitecto <span class="text-danger">*</span>
                                    </label>
                                    <input 
                                        type="text"
                                        class="form-control"
                                        placeholder="Nombre completo..."
                                        t-model="state.newArchitectName"
                                    />
                                </div>
                                <div class="row">
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">RFC (opcional)</label>
                                        <input 
                                            type="text"
                                            class="form-control"
                                            placeholder="RFC..."
                                            t-model="state.newArchitectVat"
                                        />
                                    </div>
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">Referencia (opcional)</label>
                                        <input 
                                            type="text"
                                            class="form-control"
                                            placeholder="Código de referencia..."
                                            t-model="state.newArchitectRef"
                                        />
                                    </div>
                                </div>
                                <button 
                                    class="btn btn-secondary w-100"
                                    t-on-click="createArchitect"
                                >
                                    <i class="fa fa-plus-circle me-2"></i>
                                    Crear Arquitecto
                                </button>
                            </div>
                        </div>
                    </t>
                </div>
                
                <!-- PASO 4: PRECIOS -->
                <div class="step-content" t-if="state.currentStep === 4">
                    <h5 class="mb-3">
                        <i class="fa fa-dollar text-secondary me-2"></i>
                        Configurar Precios
                    </h5>
                    
                    <div class="mb-3">
                        <label class="form-label fw-bold">Divisa *</label>
                        <select class="form-select" t-model="state.selectedCurrency" t-on-change="onCurrencyChange">
                            <option value="USD">USD - Dólares</option>
                            <option value="MXN">MXN - Pesos</option>
                        </select>
                    </div>
                    
                    <t t-foreach="Object.entries(props.productGroups)" t-as="entry" t-key="entry[0]">
                        <t t-set="productId" t-value="entry[0]"/>
                        <t t-set="group" t-value="entry[1]"/>
                        
                        <div class="card border mb-3">
                            <div class="card-body">
                                <h6><t t-esc="group.name"/></h6>
                                <small class="text-muted">
                                    <t t-esc="formatNumber(group.total_quantity)"/> m² • 
                                    <t t-esc="group.lots.length"/> lotes
                                </small>
                                
                                <div class="mt-3">
                                    <label class="form-label">Precio por m² *</label>
                                    <t t-if="state.productPriceOptions[productId] and state.productPriceOptions[productId].length > 0">
                                        <select 
                                            class="form-select mb-2"
                                            t-model.number="state.productPrices[productId]"
                                            t-on-change="(ev) => this.onPriceChange(productId, ev.target.value)"
                                        >
                                            <t t-foreach="state.productPriceOptions[productId]" t-as="option" t-key="option_index">
                                                <option t-att-value="option.value">
                                                    <t t-esc="option.label"/> - <t t-esc="formatNumber(option.value)"/>
                                                </option>
                                            </t>
                                        </select>
                                    </t>
                                    <input 
                                        type="number"
                                        class="form-control"
                                        placeholder="Precio personalizado"
                                        t-model.number="state.productPrices[productId]"
                                        t-on-change="(ev) => this.onPriceChange(productId, ev.target.value)"
                                        step="0.01"
                                    />
                                </div>
                            </div>
                        </div>
                    </t>
                </div>
                
                <!-- PASO 5: CONFIRMAR -->
                <div class="step-content" t-if="state.currentStep === 5">
                    <h5 class="mb-3">
                        <i class="fa fa-check-circle text-success me-2"></i>
                        Confirmar Apartados
                    </h5>
                    
                    <div class="card border mb-3">
                        <div class="card-body">
                            <h6 class="card-title mb-3">Resumen</h6>
                            
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <strong>Cliente:</strong><br/>
                                    <t t-esc="state.selectedPartnerName"/>
                                </div>
                                <div class="col-md-6">
                                    <strong>Proyecto:</strong><br/>
                                    <t t-esc="state.selectedProjectName"/>
                                </div>
                                <div class="col-md-6">
                                    <strong>Arquitecto:</strong><br/>
                                    <t t-esc="state.selectedArchitectName"/>
                                </div>
                                <div class="col-md-6">
                                    <strong>Vendedor:</strong><br/>
                                    <span class="badge bg-info text-dark">
                                        <i class="fa fa-user me-1"></i>
                                        <t t-esc="state.sellerName"/>
                                    </span>
                                </div>
                                <div class="col-md-6">
                                    <strong>Divisa:</strong><br/>
                                    <t t-esc="state.selectedCurrency"/>
                                </div>
                                <div class="col-md-6">
                                    <strong>Total de lotes:</strong><br/>
                                    <t t-esc="props.selectedLots.length"/>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="card border mb-3">
                        <div class="card-body">
                            <h6 class="card-title mb-3">Precios Configurados</h6>
                            <table class="table table-sm">
                                <thead>
                                    <tr>
                                        <th>Producto</th>
                                        <th class="text-end">Cantidad</th>
                                        <th class="text-end">Precio/m²</th>
                                        <th class="text-end">Total Estimado</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="Object.entries(props.productGroups)" t-as="entry" t-key="entry[0]">
                                        <t t-set="productId" t-value="entry[0]"/>
                                        <t t-set="group" t-value="entry[1]"/>
                                        <tr>
                                            <td><t t-esc="group.name"/></td>
                                            <td class="text-end"><t t-esc="formatNumber(group.total_quantity)"/> m²</td>
                                            <td class="text-end"><t t-esc="formatNumber(state.productPrices[productId])"/> <t t-esc="state.selectedCurrency"/></td>
                                            <td class="text-end"><t t-esc="formatNumber(group.total_quantity * state.productPrices[productId])"/> <t t-esc="state.selectedCurrency"/></td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <label class="form-label fw-bold">
                            <i class="fa fa-commenting text-secondary me-2"></i>
                            Notas (opcional)
                        </label>
                        <textarea 
                            class="form-control"
                            rows="3"
                            placeholder="Observaciones adicionales..."
                            t-model="state.notas"
                        ></textarea>
                    </div>
                    
                    <div class="alert alert-light border">
                        <div class="d-flex align-items-start">
                            <i class="fa fa-clock-o fa-2x text-muted me-3"></i>
                            <div>
                                <strong class="d-block mb-1">Duración del Apartado</strong>
                                <p class="mb-0">
                                    Los apartados tendrán una duración de <strong>5 días hábiles</strong> a partir de hoy.
                                    Podrás renovarlos desde la gestión de apartados si es necesario.
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <t t-set-slot="footer">
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="prevStep"
                    t-if="state.currentStep > 1 and state.currentStep &lt; 5"
                >
                    <i class="fa fa-chevron-left me-2"></i>
                    Anterior
                </button>
                
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="props.close"
                    t-if="state.currentStep === 1"
                >
                    <i class="fa fa-times me-2"></i>
                    Cancelar
                </button>
                
                <button 
                    class="btn btn-secondary btn-lg"
                    t-on-click="nextStep"
                    t-if="state.currentStep &lt; 5"
                >
                    Siguiente
                    <i class="fa fa-chevron-right ms-2"></i>
                </button>
                
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="prevStep"
                    t-if="state.currentStep === 5"
                >
                    <i class="fa fa-chevron-left me-2"></i>
                    Anterior
                </button>
                
                <button 
                    class="btn btn-primary btn-lg"
                    t-on-click="createHolds"
                    t-if="state.currentStep === 5"
                    t-att-disabled="state.isCreating"
                >
                    <t t-if="!state.isCreating">
                        <i class="fa fa-lock me-2"></i>
                        Apartar Todo
                    </t>
                    <t t-else="">
                        <i class="fa fa-spinner fa-spin me-2"></i>
                        Apartando...
                    </t>
                </button>
            </t>
        </Dialog>
    </t>
    
</templates>```

## ./static/src/components/dialogs/sale_order_wizard/sale_order_wizard.js
```js
/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class SaleOrderWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        
        this.productIds = Object.keys(this.props.productGroups).map(id => parseInt(id));
        
        this.state = useState({
            // Cliente
            searchPartnerTerm: '',
            partners: [],
            selectedPartnerId: null,
            selectedPartnerName: '',
            showCreatePartner: false,
            newPartnerName: '',
            newPartnerVat: '',
            newPartnerRef: '',
            
            // Proyecto
            searchProjectTerm: '',
            projects: [],
            selectedProjectId: null,
            selectedProjectName: '',
            showCreateProject: false,
            newProjectName: '',
            
            // Arquitecto
            searchArchitectTerm: '',
            architects: [],
            selectedArchitectId: null,
            selectedArchitectName: '',
            showCreateArchitect: false,
            newArchitectName: '',
            newArchitectVat: '',
            newArchitectRef: '',
            
            // Precios
            selectedCurrency: 'USD',
            pricelists: [],
            selectedPricelistId: null,
            productPrices: {},
            productPriceOptions: {},
            
            // Servicios
            searchServiceTerm: '',
            availableServices: [],
            selectedServices: [], // Array de {product_id, name, quantity, price_unit, display_name}
            
            // Notas
            notas: '',
            applyTax: true,
            
            // UI
            isCreating: false,
            currentStep: 1,
        });
        
        this.searchTimeout = null;
        this.loadPricelists();
    }
    
    async loadPricelists() {
        try {
            const pricelists = await this.orm.searchRead(
                "product.pricelist",
                [['name', 'in', ['USD', 'MXN']]],
                ['id', 'name', 'currency_id']
            );
            this.state.pricelists = pricelists;
            
            const usd = pricelists.find(p => p.name === 'USD');
            if (usd) {
                this.state.selectedPricelistId = usd.id;
                this.state.selectedCurrency = 'USD';
            }
            
            await this.loadAllProductPrices();
        } catch (error) {
            console.error("Error cargando listas de precios:", error);
            this.notification.add("Error al cargar listas de precios", { type: "warning" });
        }
    }
    
    async loadAllProductPrices() {
        for (const productId of this.productIds) {
            try {
                const prices = await this.orm.call(
                    "product.template",
                    "get_custom_prices",
                    [],
                    {
                        product_id: productId,
                        currency_code: this.state.selectedCurrency
                    }
                );
                
                this.state.productPriceOptions[productId] = prices;
                
                if (prices.length > 0 && !this.state.productPrices[productId]) {
                    this.state.productPrices[productId] = prices[0].value;
                }
            } catch (error) {
                console.error(`Error cargando precios para producto ${productId}:`, error);
            }
        }
    }
    
    async onCurrencyChange(ev) {
        const pricelistName = ev.target.value;
        this.state.selectedCurrency = pricelistName;
        
        const pricelist = this.state.pricelists.find(p => p.name === pricelistName);
        if (pricelist) {
            this.state.selectedPricelistId = pricelist.id;
        }
        
        this.state.productPrices = {};
        this.state.productPriceOptions = {};
        
        await this.loadAllProductPrices();
    }
    
    onPriceChange(productId, value) {
        const numValue = parseFloat(value);
        const options = this.state.productPriceOptions[productId] || [];
        
        if (options.length === 0) {
            this.state.productPrices[productId] = numValue;
            return;
        }
        
        const minPrice = Math.min(...options.map(opt => opt.value));
        
        if (numValue < minPrice) {
            this.notification.add(
                `El precio no puede ser menor a ${this.formatNumber(minPrice)}`,
                { type: "warning" }
            );
            this.state.productPrices[productId] = minPrice;
        } else {
            this.state.productPrices[productId] = numValue;
        }
    }
    
    // ========== SERVICIOS ==========
    
    onSearchService(ev) {
        const value = ev.target.value;
        this.state.searchServiceTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchServices();
        }, 300);
    }
    
    async searchServices() {
        try {
            const services = await this.orm.searchRead(
                "product.product",
                [
                    ['type', '=', 'service'],
                    ['sale_ok', '=', true],
                    '|',
                    ['name', 'ilike', this.state.searchServiceTerm.trim()],
                    ['default_code', 'ilike', this.state.searchServiceTerm.trim()]
                ],
                ['id', 'display_name', 'list_price', 'uom_id'],
                { limit: 20 }
            );
            
            this.state.availableServices = services;
        } catch (error) {
            console.error("Error buscando servicios:", error);
            this.notification.add("Error al buscar servicios", { type: "danger" });
        }
    }
    
    addService(service) {
        const exists = this.state.selectedServices.find(s => s.product_id === service.id);
        if (exists) {
            this.notification.add("Este servicio ya fue agregado", { type: "warning" });
            return;
        }
        
        this.state.selectedServices.push({
            product_id: service.id,
            display_name: service.display_name,
            quantity: 1,
            price_unit: service.list_price,
            uom_name: service.uom_id[1]
        });
        
        this.state.searchServiceTerm = '';
        this.state.availableServices = [];
    }
    
    removeService(index) {
        this.state.selectedServices.splice(index, 1);
    }
    
    updateServiceQuantity(index, value) {
        const qty = parseFloat(value) || 1;
        this.state.selectedServices[index].quantity = qty > 0 ? qty : 1;
    }
    
    updateServicePrice(index, value) {
        const price = parseFloat(value) || 0;
        this.state.selectedServices[index].price_unit = price >= 0 ? price : 0;
    }
    
    getTotalServices() {
        return this.state.selectedServices.reduce((sum, s) => sum + (s.quantity * s.price_unit), 0);
    }
    
    // ========== CLIENTE ==========
    
    onSearchPartner(ev) {
        const value = ev.target.value;
        this.state.searchPartnerTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchPartners();
        }, 300);
    }
    
    async searchPartners() {
        try {
            const partners = await this.orm.call(
                "stock.quant",
                "search_partners",
                [],
                { name: this.state.searchPartnerTerm.trim() }
            );
            
            this.state.partners = partners;
        } catch (error) {
            console.error("Error buscando clientes:", error);
            this.notification.add("Error al buscar clientes", { type: "danger" });
        }
    }
    
    selectPartner(partner) {
        this.state.selectedPartnerId = partner.id;
        this.state.selectedPartnerName = partner.display_name;
        this.state.showCreatePartner = false;
    }
    
    toggleCreatePartner() {
        this.state.showCreatePartner = !this.state.showCreatePartner;
        if (this.state.showCreatePartner) {
            this.state.selectedPartnerId = null;
            this.state.selectedPartnerName = '';
        }
    }
    
    async createPartner() {
        if (!this.state.newPartnerName.trim()) {
            this.notification.add("El nombre del cliente es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_partner",
                [],
                {
                    name: this.state.newPartnerName.trim(),
                    vat: this.state.newPartnerVat.trim(),
                    ref: this.state.newPartnerRef.trim()
                }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectPartner(result.partner);
                this.notification.add(`Cliente "${result.partner.name}" creado exitosamente`, { type: "success" });
                this.state.newPartnerName = '';
                this.state.newPartnerVat = '';
                this.state.newPartnerRef = '';
            }
        } catch (error) {
            console.error("Error creando cliente:", error);
            this.notification.add("Error al crear cliente", { type: "danger" });
        }
    }
    
    // ========== PROYECTO ==========
    
    onSearchProject(ev) {
        const value = ev.target.value;
        this.state.searchProjectTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchProjects();
        }, 300);
    }
    
    async searchProjects() {
        try {
            const projects = await this.orm.call(
                "stock.quant",
                "get_projects",
                [],
                { search_term: this.state.searchProjectTerm.trim() }
            );
            
            this.state.projects = projects;
        } catch (error) {
            console.error("Error buscando proyectos:", error);
            this.notification.add("Error al buscar proyectos", { type: "danger" });
        }
    }
    
    selectProject(project) {
        this.state.selectedProjectId = project.id;
        this.state.selectedProjectName = project.name;
        this.state.showCreateProject = false;
    }
    
    toggleCreateProject() {
        this.state.showCreateProject = !this.state.showCreateProject;
        if (this.state.showCreateProject) {
            this.state.selectedProjectId = null;
            this.state.selectedProjectName = '';
        }
    }
    
    async createProject() {
        if (!this.state.newProjectName.trim()) {
            this.notification.add("El nombre del proyecto es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_project",
                [],
                { name: this.state.newProjectName.trim() }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectProject(result.project);
                this.notification.add(`Proyecto "${result.project.name}" creado exitosamente`, { type: "success" });
                this.state.newProjectName = '';
            }
        } catch (error) {
            console.error("Error creando proyecto:", error);
            this.notification.add("Error al crear proyecto", { type: "danger" });
        }
    }
    
    // ========== ARQUITECTO ==========
    
    onSearchArchitect(ev) {
        const value = ev.target.value;
        this.state.searchArchitectTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchArchitects();
        }, 300);
    }
    
    async searchArchitects() {
        try {
            const architects = await this.orm.call(
                "stock.quant",
                "get_architects",
                [],
                { search_term: this.state.searchArchitectTerm.trim() }
            );
            
            this.state.architects = architects;
        } catch (error) {
            console.error("Error buscando arquitectos:", error);
            this.notification.add("Error al buscar arquitectos", { type: "danger" });
        }
    }
    
    selectArchitect(architect) {
        this.state.selectedArchitectId = architect.id;
        this.state.selectedArchitectName = architect.display_name;
        this.state.showCreateArchitect = false;
    }
    
    toggleCreateArchitect() {
        this.state.showCreateArchitect = !this.state.showCreateArchitect;
        if (this.state.showCreateArchitect) {
            this.state.selectedArchitectId = null;
            this.state.selectedArchitectName = '';
        }
    }
    
    async createArchitect() {
        if (!this.state.newArchitectName.trim()) {
            this.notification.add("El nombre del arquitecto es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_architect",
                [],
                {
                    name: this.state.newArchitectName.trim(),
                    vat: this.state.newArchitectVat.trim(),
                    ref: this.state.newArchitectRef.trim()
                }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectArchitect(result.architect);
                this.notification.add(`Arquitecto "${result.architect.name}" creado exitosamente`, { type: "success" });
                this.state.newArchitectName = '';
                this.state.newArchitectVat = '';
                this.state.newArchitectRef = '';
            }
        } catch (error) {
            console.error("Error creando arquitecto:", error);
            this.notification.add("Error al crear arquitecto", { type: "danger" });
        }
    }
    
    // ========== NAVEGACIÓN ==========
    
    nextStep() {
        if (this.state.currentStep === 1 && !this.state.selectedPartnerId) {
            this.notification.add("Debe seleccionar o crear un cliente", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 2 && !this.state.selectedProjectId) {
            this.notification.add("Debe seleccionar o crear un proyecto", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 3 && !this.state.selectedArchitectId) {
            this.notification.add("Debe seleccionar o crear un arquitecto", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 4) {
            const hasInvalidPrice = this.productIds.some(pid => {
                const price = this.state.productPrices[pid];
                return !price || price <= 0;
            });
            
            if (hasInvalidPrice) {
                this.notification.add("Debe configurar precios para todos los productos", { type: "warning" });
                return;
            }
        }
        
        if (this.state.currentStep < 6) {
            this.state.currentStep++;
        }
    }
    
    prevStep() {
        if (this.state.currentStep > 1) {
            this.state.currentStep--;
        }
    }
    
    // ========== CREAR ORDEN ==========
    
    async createSaleOrder() {
        this.state.isCreating = true;
        
        try {
            const products = [];
            
            for (const [productId, group] of Object.entries(this.props.productGroups)) {
                products.push({
                    product_id: parseInt(productId),
                    quantity: group.total_quantity,
                    price_unit: parseFloat(this.state.productPrices[productId]),
                    selected_lots: group.lots.map(lot => lot.id)
                });
            }
            
            const services = this.state.selectedServices.map(s => ({
                product_id: s.product_id,
                quantity: s.quantity,
                price_unit: s.price_unit
            }));
            
            let finalNotes = this.state.notas || '';
            
            if (this.state.selectedProjectName) {
                finalNotes += `\n\n=== INFORMACIÓN DEL PROYECTO ===\n`;
                finalNotes += `Proyecto: ${this.state.selectedProjectName}\n`;
            }
            
            if (this.state.selectedArchitectName) {
                finalNotes += `Arquitecto: ${this.state.selectedArchitectName}\n`;
            }
            
            if (!this.state.applyTax) {
                finalNotes += '\n\n⚠️ NOTA IMPORTANTE: El IVA se agregará posteriormente por cuestiones legales.';
            }
            
            const result = await this.orm.call("sale.order", "create_from_shopping_cart", [], {
                partner_id: this.state.selectedPartnerId,
                products: products,
                services: services,
                notes: finalNotes,
                pricelist_id: this.state.selectedPricelistId,
                apply_tax: this.state.applyTax
            });
            
            if (result.success) {
                this.notification.add(`Orden ${result.order_name} creada exitosamente`, { type: "success" });
                this.props.onSuccess();
                this.props.close();
                
                // Abrir la orden recién creada
                this.action.doAction({
                    type: 'ir.actions.act_window',
                    res_model: 'sale.order',
                    res_id: result.order_id,
                    views: [[false, 'form']],
                    target: 'current',
                });
            }
        } catch (error) {
            console.error("Error creando orden:", error);
            this.notification.add(error.message || "Error al crear orden", { type: "danger" });
        } finally {
            this.state.isCreating = false;
        }
    }
    
    formatNumber(num) {
        return new Intl.NumberFormat('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num);
    }
}

SaleOrderWizard.template = "inventory_shopping_cart.SaleOrderWizard";
SaleOrderWizard.components = { Dialog };
SaleOrderWizard.props = {
    close: Function,
    productGroups: Object,
    onSuccess: Function,
};```

## ./static/src/components/dialogs/sale_order_wizard/sale_order_wizard.scss
```scss
/* ./static/src/components/dialogs/sale_order_wizard/sale_order_wizard.scss */
.sale-order-wizard-content {
  .steps-indicator {
    padding: 16px 0;
    
    .step-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      flex: 1;
      
      .step-number {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: #E0E0E0;
        color: #808080;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 14px;
        transition: all 0.3s ease;
      }
      
      .step-label {
        font-size: 12px;
        color: #808080;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        transition: all 0.3s ease;
      }
      
      &.active {
        .step-number {
          background: #017E84;
          color: white;
        }
        
        .step-label {
          color: #017E84;
        }
      }
      
      &.completed {
        .step-number {
          background: #21B799;
          color: white;
        }
        
        .step-label {
          color: #21B799;
        }
      }
    }
    
    .step-line {
      flex: 1;
      height: 2px;
      background: #E0E0E0;
      margin: 0 8px;
      align-self: center;
      transition: all 0.3s ease;
      margin-top: -24px;
      
      &.active {
        background: #017E84;
      }
    }
  }
  
  .step-content {
    min-height: 400px;
    animation: fadeIn 0.3s ease-in;
  }
  
  // Estilos específicos para la tabla de precios
  .table-responsive {
    border-radius: 8px;
    border: 1px solid #dee2e6;
    
    .table {
      margin-bottom: 0;
      
      thead {
        &.sticky-top {
          position: sticky;
          top: 0;
          z-index: 10;
        }
        
        th {
          background-color: #f8f9fa;
          border-bottom: 2px solid #dee2e6;
          font-weight: 600;
          padding: 12px;
        }
      }
      
      tbody {
        tr {
          transition: background-color 0.2s ease;
          
          &:hover {
            background-color: #f8f9fa;
          }
          
          td {
            padding: 12px;
            vertical-align: middle;
          }
        }
      }
      
      tfoot {
        th {
          background-color: #f8f9fa;
          border-top: 2px solid #dee2e6;
          padding: 12px;
          font-weight: 700;
        }
      }
    }
    
    .form-select-sm,
    .form-control-sm {
      font-size: 0.875rem;
    }
  }
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}```

## ./static/src/components/dialogs/sale_order_wizard/sale_order_wizard.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    
    <t t-name="inventory_shopping_cart.SaleOrderWizard" owl="1">
        <Dialog size="'xl'">
            <div class="sale-order-wizard-content">
                <div class="alert alert-light border-start border-4 border-primary mb-4">
                    <div class="d-flex align-items-center">
                        <i class="fa fa-file-text fa-2x text-primary me-3"></i>
                        <div>
                            <h5 class="mb-1 fw-bold">Crear Orden de Venta</h5>
                            <small class="text-muted">
                                <i class="fa fa-cubes me-1"></i>
                                <strong t-esc="Object.keys(props.productGroups).length"></strong> productos • 
                                <strong t-esc="Object.values(props.productGroups).reduce((sum, g) => sum + g.lots.length, 0)"></strong> lotes
                            </small>
                        </div>
                    </div>
                </div>
                
                <!-- Indicador de pasos (6 pasos) -->
                <div class="steps-indicator mb-4">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 1, completed: state.currentStep > 1 }">
                            <div class="step-number">1</div>
                            <div class="step-label">Cliente</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 1 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 2, completed: state.currentStep > 2 }">
                            <div class="step-number">2</div>
                            <div class="step-label">Proyecto</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 2 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 3, completed: state.currentStep > 3 }">
                            <div class="step-number">3</div>
                            <div class="step-label">Arquitecto</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 3 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 4, completed: state.currentStep > 4 }">
                            <div class="step-number">4</div>
                            <div class="step-label">Precios</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 4 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 5, completed: state.currentStep > 5 }">
                            <div class="step-number">5</div>
                            <div class="step-label">Servicios</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 5 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 6 }">
                            <div class="step-number">6</div>
                            <div class="step-label">Confirmar</div>
                        </div>
                    </div>
                </div>
                
                <!-- PASO 1: CLIENTE -->
                <div class="step-content" t-if="state.currentStep === 1">
                    <h5 class="mb-3">
                        <i class="fa fa-user text-primary me-2"></i>
                        Seleccionar Cliente
                    </h5>
                    
                    <div class="btn-group w-100 mb-3" role="group">
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="!state.showCreatePartner ? 'btn-primary' : 'btn-outline-primary'"
                            t-on-click="() => this.state.showCreatePartner = false"
                        >
                            <i class="fa fa-search me-2"></i>
                            Buscar Existente
                        </button>
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="state.showCreatePartner ? 'btn-primary' : 'btn-outline-primary'"
                            t-on-click="toggleCreatePartner"
                        >
                            <i class="fa fa-plus me-2"></i>
                            Crear Nuevo
                        </button>
                    </div>
                    
                    <t t-if="!state.showCreatePartner">
                        <div class="input-group mb-2">
                            <span class="input-group-text">
                                <i class="fa fa-search"></i>
                            </span>
                            <input 
                                type="text"
                                class="form-control"
                                placeholder="Buscar por nombre, RFC o referencia..."
                                t-model="state.searchPartnerTerm"
                                t-on-input="onSearchPartner"
                            />
                        </div>
                        
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedPartnerName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Cliente seleccionado:</strong><br/>
                                <t t-esc="state.selectedPartnerName"/>
                            </div>
                        </div>
                        
                        <div class="list-group" style="max-height: 300px; overflow-y: auto;" t-if="state.partners.length > 0 and !state.selectedPartnerName">
                            <t t-foreach="state.partners" t-as="partner" t-key="partner.id">
                                <button 
                                    type="button"
                                    class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                    t-on-click="() => this.selectPartner(partner)"
                                >
                                    <div>
                                        <strong t-esc="partner.name"></strong>
                                        <small class="text-muted ms-2" t-if="partner.ref">
                                            [<t t-esc="partner.ref"/>]
                                        </small>
                                        <small class="text-muted ms-2" t-if="partner.vat">
                                            RFC: <t t-esc="partner.vat"/>
                                        </small>
                                    </div>
                                    <i class="fa fa-chevron-right text-muted"></i>
                                </button>
                            </t>
                        </div>
                    </t>
                    
                    <t t-if="state.showCreatePartner">
                        <div class="card bg-light border mb-3">
                            <div class="card-body">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">
                                        Nombre del Cliente <span class="text-danger">*</span>
                                    </label>
                                    <input 
                                        type="text"
                                        class="form-control"
                                        placeholder="Nombre completo o razón social..."
                                        t-model="state.newPartnerName"
                                    />
                                </div>
                                <div class="row">
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">RFC (opcional)</label>
                                        <input 
                                            type="text"
                                            class="form-control"
                                            placeholder="RFC..."
                                            t-model="state.newPartnerVat"
                                        />
                                    </div>
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">Referencia (opcional)</label>
                                        <input 
                                            type="text"
                                            class="form-control"
                                            placeholder="Código de referencia..."
                                            t-model="state.newPartnerRef"
                                        />
                                    </div>
                                </div>
                                <button 
                                    class="btn btn-primary w-100"
                                    t-on-click="createPartner"
                                >
                                    <i class="fa fa-plus-circle me-2"></i>
                                    Crear Cliente
                                </button>
                            </div>
                        </div>
                    </t>
                </div>
                
                <!-- PASO 2: PROYECTO -->
                <div class="step-content" t-if="state.currentStep === 2">
                    <h5 class="mb-3">
                        <i class="fa fa-folder text-primary me-2"></i>
                        Seleccionar Proyecto
                    </h5>
                    
                    <div class="btn-group w-100 mb-3" role="group">
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="!state.showCreateProject ? 'btn-primary' : 'btn-outline-primary'"
                            t-on-click="() => this.state.showCreateProject = false"
                        >
                            <i class="fa fa-search me-2"></i>
                            Buscar Existente
                        </button>
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="state.showCreateProject ? 'btn-primary' : 'btn-outline-primary'"
                            t-on-click="toggleCreateProject"
                        >
                            <i class="fa fa-plus me-2"></i>
                            Crear Nuevo
                        </button>
                    </div>
                    
                    <t t-if="!state.showCreateProject">
                        <div class="input-group mb-2">
                            <span class="input-group-text">
                                <i class="fa fa-search"></i>
                            </span>
                            <input 
                                type="text"
                                class="form-control"
                                placeholder="Buscar proyecto..."
                                t-model="state.searchProjectTerm"
                                t-on-input="onSearchProject"
                            />
                        </div>
                        
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedProjectName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Proyecto seleccionado:</strong><br/>
                                <t t-esc="state.selectedProjectName"/>
                            </div>
                        </div>
                        
                        <div class="list-group" style="max-height: 300px; overflow-y: auto;" t-if="state.projects.length > 0 and !state.selectedProjectName">
                            <t t-foreach="state.projects" t-as="project" t-key="project.id">
                                <button 
                                    type="button"
                                    class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                    t-on-click="() => this.selectProject(project)"
                                >
                                    <div>
                                        <strong t-esc="project.name"></strong>
                                    </div>
                                    <i class="fa fa-chevron-right text-muted"></i>
                                </button>
                            </t>
                        </div>
                    </t>
                    
                    <t t-if="state.showCreateProject">
                        <div class="card bg-light border mb-3">
                            <div class="card-body">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">
                                        Nombre del Proyecto <span class="text-danger">*</span>
                                    </label>
                                    <input 
                                        type="text"
                                        class="form-control"
                                        placeholder="Nombre del proyecto..."
                                        t-model="state.newProjectName"
                                    />
                                </div>
                                <button 
                                    class="btn btn-primary w-100"
                                    t-on-click="createProject"
                                >
                                    <i class="fa fa-plus-circle me-2"></i>
                                    Crear Proyecto
                                </button>
                            </div>
                        </div>
                    </t>
                </div>
                
                <!-- PASO 3: ARQUITECTO -->
                <div class="step-content" t-if="state.currentStep === 3">
                    <h5 class="mb-3">
                        <i class="fa fa-user-circle text-primary me-2"></i>
                        Seleccionar Arquitecto
                    </h5>
                    
                    <div class="btn-group w-100 mb-3" role="group">
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="!state.showCreateArchitect ? 'btn-primary' : 'btn-outline-primary'"
                            t-on-click="() => this.state.showCreateArchitect = false"
                        >
                            <i class="fa fa-search me-2"></i>
                            Buscar Existente
                        </button>
                        <button 
                            type="button" 
                            class="btn"
                            t-att-class="state.showCreateArchitect ? 'btn-primary' : 'btn-outline-primary'"
                            t-on-click="toggleCreateArchitect"
                        >
                            <i class="fa fa-plus me-2"></i>
                            Crear Nuevo
                        </button>
                    </div>
                    
                    <t t-if="!state.showCreateArchitect">
                        <div class="input-group mb-2">
                            <span class="input-group-text">
                                <i class="fa fa-search"></i>
                            </span>
                            <input 
                                type="text"
                                class="form-control"
                                placeholder="Buscar arquitecto..."
                                t-model="state.searchArchitectTerm"
                                t-on-input="onSearchArchitect"
                            />
                        </div>
                        
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedArchitectName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Arquitecto seleccionado:</strong><br/>
                                <t t-esc="state.selectedArchitectName"/>
                            </div>
                        </div>
                        
                        <div class="list-group" style="max-height: 300px; overflow-y: auto;" t-if="state.architects.length > 0 and !state.selectedArchitectName">
                            <t t-foreach="state.architects" t-as="architect" t-key="architect.id">
                                <button 
                                    type="button"
                                    class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                    t-on-click="() => this.selectArchitect(architect)"
                                >
                                    <div>
                                        <strong t-esc="architect.name"></strong>
                                        <small class="text-muted ms-2" t-if="architect.ref">
                                            [<t t-esc="architect.ref"/>]
                                        </small>
                                        <small class="text-muted ms-2" t-if="architect.vat">
                                            RFC: <t t-esc="architect.vat"/>
                                        </small>
                                    </div>
                                    <i class="fa fa-chevron-right text-muted"></i>
                                </button>
                            </t>
                        </div>
                    </t>
                    
                    <t t-if="state.showCreateArchitect">
                        <div class="card bg-light border mb-3">
                            <div class="card-body">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">
                                        Nombre del Arquitecto <span class="text-danger">*</span>
                                    </label>
                                    <input 
                                        type="text"
                                        class="form-control"
                                        placeholder="Nombre completo..."
                                        t-model="state.newArchitectName"
                                    />
                                </div>
                                <div class="row">
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">RFC (opcional)</label>
                                        <input 
                                            type="text"
                                            class="form-control"
                                            placeholder="RFC..."
                                            t-model="state.newArchitectVat"
                                        />
                                    </div>
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">Referencia (opcional)</label>
                                        <input 
                                            type="text"
                                            class="form-control"
                                            placeholder="Código de referencia..."
                                            t-model="state.newArchitectRef"
                                        />
                                    </div>
                                </div>
                                <button 
                                    class="btn btn-primary w-100"
                                    t-on-click="createArchitect"
                                >
                                    <i class="fa fa-plus-circle me-2"></i>
                                    Crear Arquitecto
                                </button>
                            </div>
                        </div>
                    </t>
                </div>
                
                <!-- PASO 4: PRECIOS -->
                <div class="step-content" t-if="state.currentStep === 4">
                    <h5 class="mb-3">
                        <i class="fa fa-dollar text-primary me-2"></i>
                        Configurar Precios
                    </h5>
                    
                    <div class="row mb-4">
                        <div class="col-md-6">
                            <label class="form-label fw-bold">Divisa / Lista de Precios *</label>
                            <select 
                                class="form-select" 
                                t-model="state.selectedCurrency" 
                                t-on-change="onCurrencyChange"
                            >
                                <option value="USD">USD - Dólares</option>
                                <option value="MXN">MXN - Pesos</option>
                            </select>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label fw-bold">IVA</label>
                            <div class="form-check form-switch pt-2">
                                <input class="form-check-input" type="checkbox" role="switch" t-model="state.applyTax" id="applyTaxSwitch"/>
                                <label class="form-check-label" for="applyTaxSwitch">
                                    <t t-if="state.applyTax">Aplicar IVA</t>
                                    <t t-else="">Sin IVA (se agregará nota legal)</t>
                                </label>
                            </div>
                        </div>
                    </div>
                    
                    <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                        <table class="table table-hover">
                            <thead class="table-light sticky-top">
                                <tr>
                                    <th style="width: 35%;">Producto</th>
                                    <th class="text-end" style="width: 15%;">Cantidad</th>
                                    <th class="text-end" style="width: 15%;">Lotes</th>
                                    <th style="width: 20%;">Precio/m²</th>
                                    <th class="text-end" style="width: 15%;">Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                <t t-foreach="Object.entries(props.productGroups)" t-as="entry" t-key="entry[0]">
                                    <t t-set="productId" t-value="entry[0]"/>
                                    <t t-set="group" t-value="entry[1]"/>
                                    <tr>
                                        <td>
                                            <strong t-esc="group.name"></strong>
                                        </td>
                                        <td class="text-end">
                                            <t t-esc="formatNumber(group.total_quantity)"/> m²
                                        </td>
                                        <td class="text-end">
                                            <span class="badge bg-secondary">
                                                <t t-esc="group.lots.length"/>
                                            </span>
                                        </td>
                                        <td>
                                            <t t-if="state.productPriceOptions[productId] and state.productPriceOptions[productId].length > 0">
                                                <select 
                                                    class="form-select form-select-sm mb-1"
                                                    t-model.number="state.productPrices[productId]"
                                                    t-on-change="(ev) => this.onPriceChange(productId, ev.target.value)"
                                                >
                                                    <t t-foreach="state.productPriceOptions[productId]" t-as="option" t-key="option_index">
                                                        <option t-att-value="option.value">
                                                            <t t-esc="option.label"/> - <t t-esc="formatNumber(option.value)"/>
                                                        </option>
                                                    </t>
                                                </select>
                                            </t>
                                            <input 
                                                type="number"
                                                class="form-control form-control-sm"
                                                placeholder="Personalizado"
                                                t-model.number="state.productPrices[productId]"
                                                t-on-change="(ev) => this.onPriceChange(productId, ev.target.value)"
                                                step="0.01"
                                            />
                                        </td>
                                        <td class="text-end">
                                            <strong t-esc="formatNumber(group.total_quantity * (state.productPrices[productId] || 0))"></strong>
                                            <small class="text-muted ms-1"><t t-esc="state.selectedCurrency"/></small>
                                        </td>
                                    </tr>
                                </t>
                            </tbody>
                            <tfoot class="table-light">
                                <tr>
                                    <th>TOTAL PRODUCTOS</th>
                                    <th class="text-end">
                                        <t t-esc="formatNumber(Object.values(props.productGroups).reduce((sum, g) => sum + g.total_quantity, 0))"/> m²
                                    </th>
                                    <th class="text-end">
                                        <span class="badge bg-primary">
                                            <t t-esc="Object.values(props.productGroups).reduce((sum, g) => sum + g.lots.length, 0)"/>
                                        </span>
                                    </th>
                                    <th></th>
                                    <th class="text-end">
                                        <strong class="text-primary h5 mb-0">
                                            <t t-esc="formatNumber(Object.entries(props.productGroups).reduce((sum, [pid, g]) => sum + (g.total_quantity * (state.productPrices[pid] || 0)), 0))"/>
                                            <small><t t-esc="state.selectedCurrency"/></small>
                                        </strong>
                                    </th>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </div>
                
                <!-- PASO 5: SERVICIOS -->
                <div class="step-content" t-if="state.currentStep === 5">
                    <h5 class="mb-3">
                        <i class="fa fa-wrench text-primary me-2"></i>
                        Agregar Servicios (Opcional)
                    </h5>
                    
                    <div class="alert alert-info mb-3">
                        <i class="fa fa-info-circle me-2"></i>
                        Agrega servicios como fletes, maniobras, seguros, etc. Puedes continuar sin agregar servicios si no los necesitas.
                    </div>
                    
                    <!-- Buscador de servicios -->
                    <div class="card border mb-3">
                        <div class="card-body">
                            <h6 class="card-title mb-3">Buscar Servicio</h6>
                            <div class="input-group mb-2">
                                <span class="input-group-text">
                                    <i class="fa fa-search"></i>
                                </span>
                                <input 
                                    type="text"
                                    class="form-control"
                                    placeholder="Buscar por nombre o código..."
                                    t-model="state.searchServiceTerm"
                                    t-on-input="onSearchService"
                                />
                            </div>
                            
                            <div class="list-group" style="max-height: 200px; overflow-y: auto;" t-if="state.availableServices.length > 0">
                                <t t-foreach="state.availableServices" t-as="service" t-key="service.id">
                                    <button 
                                        type="button"
                                        class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                        t-on-click="() => this.addService(service)"
                                    >
                                        <div>
                                            <strong t-esc="service.display_name"></strong>
                                            <br/>
                                            <small class="text-muted">
                                                Precio: <t t-esc="formatNumber(service.list_price)"/> <t t-esc="state.selectedCurrency"/>
                                            </small>
                                        </div>
                                        <i class="fa fa-plus-circle text-primary"></i>
                                    </button>
                                </t>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Lista de servicios seleccionados -->
                    <div class="card border" t-if="state.selectedServices.length > 0">
                        <div class="card-body">
                            <h6 class="card-title mb-3">Servicios Seleccionados</h6>
                            <div class="table-responsive">
                                <table class="table table-sm">
                                    <thead class="table-light">
                                        <tr>
                                            <th style="width: 40%;">Servicio</th>
                                            <th class="text-center" style="width: 20%;">Cantidad</th>
                                            <th class="text-end" style="width: 20%;">Precio Unit.</th>
                                            <th class="text-end" style="width: 15%;">Total</th>
                                            <th style="width: 5%;"></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <t t-foreach="state.selectedServices" t-as="service" t-key="service_index">
                                            <tr>
                                                <td>
                                                    <strong t-esc="service.display_name"></strong>
                                                    <br/>
                                                    <small class="text-muted" t-esc="service.uom_name"></small>
                                                </td>
                                                <td class="text-center">
                                                    <input 
                                                        type="number"
                                                        class="form-control form-control-sm text-center"
                                                        t-model.number="service.quantity"
                                                        t-on-change="(ev) => this.updateServiceQuantity(service_index, ev.target.value)"
                                                        min="0.01"
                                                        step="0.01"
                                                        style="width: 80px; display: inline-block;"
                                                    />
                                                </td>
                                                <td class="text-end">
                                                    <input 
                                                        type="number"
                                                        class="form-control form-control-sm text-end"
                                                        t-model.number="service.price_unit"
                                                        t-on-change="(ev) => this.updateServicePrice(service_index, ev.target.value)"
                                                        min="0"
                                                        step="0.01"
                                                        style="width: 100px; display: inline-block;"
                                                    />
                                                </td>
                                                <td class="text-end">
                                                    <strong t-esc="formatNumber(service.quantity * service.price_unit)"></strong>
                                                </td>
                                                <td class="text-center">
                                                    <button 
                                                        type="button"
                                                        class="btn btn-sm btn-link text-danger p-0"
                                                        t-on-click="() => this.removeService(service_index)"
                                                        title="Eliminar"
                                                    >
                                                        <i class="fa fa-trash"></i>
                                                    </button>
                                                </td>
                                            </tr>
                                        </t>
                                    </tbody>
                                    <tfoot class="table-light">
                                        <tr>
                                            <th colspan="3">SUBTOTAL SERVICIOS</th>
                                            <th class="text-end">
                                                <strong class="text-success">
                                                    <t t-esc="formatNumber(getTotalServices())"/>
                                                    <small><t t-esc="state.selectedCurrency"/></small>
                                                </strong>
                                            </th>
                                            <th></th>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>
                    </div>
                    
                    <div class="alert alert-light mt-3" t-if="state.selectedServices.length === 0">
                        <i class="fa fa-info-circle me-2"></i>
                        No has agregado ningún servicio. Puedes continuar o buscar servicios arriba.
                    </div>
                </div>
                
                <!-- PASO 6: CONFIRMAR -->
                <div class="step-content" t-if="state.currentStep === 6">
                    <h5 class="mb-3">
                        <i class="fa fa-check-circle text-success me-2"></i>
                        Confirmar Orden
                    </h5>
                    
                    <!-- Resumen general -->
                    <div class="card border mb-3">
                        <div class="card-body">
                            <h6 class="card-title mb-3">Resumen General</h6>
                            
                            <div class="row g-3 mb-3">
                                <div class="col-md-4">
                                    <strong>Cliente:</strong><br/>
                                    <t t-esc="state.selectedPartnerName"/>
                                </div>
                                <div class="col-md-4">
                                    <strong>Proyecto:</strong><br/>
                                    <t t-esc="state.selectedProjectName"/>
                                </div>
                                <div class="col-md-4">
                                    <strong>Arquitecto:</strong><br/>
                                    <t t-esc="state.selectedArchitectName"/>
                                </div>
                                <div class="col-md-4">
                                    <strong>Divisa:</strong><br/>
                                    <span class="badge bg-primary">
                                        <t t-esc="state.selectedCurrency"/>
                                    </span>
                                </div>
                                <div class="col-md-4">
                                    <strong>IVA:</strong><br/>
                                    <span t-if="state.applyTax" class="badge bg-success">Incluido</span>
                                    <span t-else="" class="badge bg-warning text-dark">No incluido</span>
                                </div>
                                <div class="col-md-4">
                                    <strong>Total de productos:</strong><br/>
                                    <t t-esc="Object.keys(props.productGroups).length"/>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Detalle de productos -->
                    <div class="card border mb-3">
                        <div class="card-body">
                            <h6 class="card-title mb-3">Productos</h6>
                            <div class="table-responsive" style="max-height: 200px; overflow-y: auto;">
                                <table class="table table-sm">
                                    <thead class="table-light">
                                        <tr>
                                            <th>Producto</th>
                                            <th class="text-end">Cantidad</th>
                                            <th class="text-end">Precio Unit.</th>
                                            <th class="text-end">Total</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <t t-foreach="Object.entries(props.productGroups)" t-as="entry" t-key="entry[0]">
                                            <t t-set="productId" t-value="entry[0]"/>
                                            <t t-set="group" t-value="entry[1]"/>
                                            <tr>
                                                <td><t t-esc="group.name"/></td>
                                                <td class="text-end"><t t-esc="formatNumber(group.total_quantity)"/> m²</td>
                                                <td class="text-end"><t t-esc="formatNumber(state.productPrices[productId])"/></td>
                                                <td class="text-end"><t t-esc="formatNumber(group.total_quantity * state.productPrices[productId])"/></td>
                                            </tr>
                                        </t>
                                    </tbody>
                                    <tfoot class="table-light">
                                        <tr>
                                            <th>SUBTOTAL PRODUCTOS</th>
                                            <th class="text-end">
                                                <t t-esc="formatNumber(Object.values(props.productGroups).reduce((sum, g) => sum + g.total_quantity, 0))"/> m²
                                            </th>
                                            <th></th>
                                            <th class="text-end">
                                                <strong class="text-primary">
                                                    <t t-esc="formatNumber(Object.entries(props.productGroups).reduce((sum, [pid, g]) => sum + (g.total_quantity * state.productPrices[pid]), 0))"/>
                                                    <t t-esc="state.selectedCurrency"/>
                                                </strong>
                                            </th>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Detalle de servicios -->
                    <div class="card border mb-3" t-if="state.selectedServices.length > 0">
                        <div class="card-body">
                            <h6 class="card-title mb-3">Servicios</h6>
                            <div class="table-responsive">
                                <table class="table table-sm">
                                    <thead class="table-light">
                                        <tr>
                                            <th>Servicio</th>
                                            <th class="text-end">Cantidad</th>
                                            <th class="text-end">Precio Unit.</th>
                                            <th class="text-end">Total</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <t t-foreach="state.selectedServices" t-as="service" t-key="service_index">
                                            <tr>
                                                <td><t t-esc="service.display_name"/></td>
                                                <td class="text-end"><t t-esc="formatNumber(service.quantity)"/></td>
                                                <td class="text-end"><t t-esc="formatNumber(service.price_unit)"/></td>
                                                <td class="text-end"><t t-esc="formatNumber(service.quantity * service.price_unit)"/></td>
                                            </tr>
                                        </t>
                                    </tbody>
                                    <tfoot class="table-light">
                                        <tr>
                                            <th colspan="3">SUBTOTAL SERVICIOS</th>
                                            <th class="text-end">
                                                <strong class="text-success">
                                                    <t t-esc="formatNumber(getTotalServices())"/>
                                                    <t t-esc="state.selectedCurrency"/>
                                                </strong>
                                            </th>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Total general -->
                    <div class="card border-primary border-2 mb-3">
                        <div class="card-body bg-light">
                            <div class="d-flex justify-content-between align-items-center">
                                <h4 class="mb-0">TOTAL GENERAL</h4>
                                <h3 class="mb-0 text-primary">
                                    <t t-esc="formatNumber(Object.entries(props.productGroups).reduce((sum, [pid, g]) => sum + (g.total_quantity * state.productPrices[pid]), 0) + getTotalServices())"/>
                                    <span class="h5"><t t-esc="state.selectedCurrency"/></span>
                                </h3>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Notas -->
                    <div class="mb-3">
                        <label class="form-label fw-bold">
                            <i class="fa fa-commenting text-primary me-2"></i>
                            Observaciones (opcional)
                        </label>
                        <textarea 
                            class="form-control"
                            rows="3"
                            placeholder="Observaciones adicionales..."
                            t-model="state.notas"
                        ></textarea>
                    </div>
                </div>
            </div>

            <t t-set-slot="footer">
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="prevStep"
                    t-if="state.currentStep > 1 and state.currentStep &lt; 6"
                >
                    <i class="fa fa-chevron-left me-2"></i>
                    Anterior
                </button>
                
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="props.close"
                    t-if="state.currentStep === 1"
                >
                    <i class="fa fa-times me-2"></i>
                    Cancelar
                </button>
                
                <button 
                    class="btn btn-primary btn-lg"
                    t-on-click="nextStep"
                    t-if="state.currentStep &lt; 6"
                >
                    Siguiente
                    <i class="fa fa-chevron-right ms-2"></i>
                </button>
                
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="prevStep"
                    t-if="state.currentStep === 6"
                >
                    <i class="fa fa-chevron-left me-2"></i>
                    Anterior
                </button>
                
                <button 
                    class="btn btn-success btn-lg"
                    t-on-click="createSaleOrder"
                    t-if="state.currentStep === 6"
                    t-att-disabled="state.isCreating"
                >
                    <t t-if="!state.isCreating">
                        <i class="fa fa-check me-2"></i>
                        Crear y Abrir Orden
                    </t>
                    <t t-else="">
                        <i class="fa fa-spinner fa-spin me-2"></i>
                        Creando...
                    </t>
                </button>
            </t>
        </Dialog>
    </t>
    
</templates>```

## ./static/src/components/floating_bar/floating_bar.js
```js
/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { CartDialog } from "../dialogs/cart_dialog/cart_dialog";
import { HoldWizard } from "../dialogs/hold_wizard/hold_wizard";
import { SaleOrderWizard } from "../dialogs/sale_order_wizard/sale_order_wizard";

const InventoryVisualController = registry.category("actions").get("inventory_visual_enhanced");

patch(InventoryVisualController.prototype, {
    async openCartDialog() {
        if (this.cart.totalLots === 0) {
            this.notification.add("El carrito está vacío", { type: "warning" });
            return;
        }
        
        await this.syncCartToDB();
        
        this.dialog.add(CartDialog, {
            cart: this.cart,
            onRemoveHolds: () => this.removeLotsWithHold(),
            onCreateHolds: () => this.openHoldWizard(),
            onCreateSaleOrder: () => this.openSaleOrderWizard()
        });
    },
    
    async openHoldWizard() {
        await this.syncCartToDB();
        
        this.dialog.add(HoldWizard, {
            selectedLots: this.cart.items.map(item => item.id),
            productGroups: this.cart.productGroups,
            onSuccess: async () => {
                this.clearCart();
                await this.searchProducts();
            }
        });
    },
    
    async openSaleOrderWizard() {
        const lotsWithHold = this.cart.items.filter(item => item.tiene_hold);
        
        if (lotsWithHold.length > 0) {
            this.notification.add("Hay lotes apartados en el carrito. Use 'Eliminar Apartados' primero.", { type: "warning", sticky: true });
            return;
        }
        
        await this.syncCartToDB();
        
        this.dialog.add(SaleOrderWizard, {
            productGroups: this.cart.productGroups,
            onSuccess: () => {
                this.clearCart();
            }
        });
    }
});

import { ProductRow } from "@inventory_visual_enhanced/components/product_row/product_row";
patch(ProductRow.prototype, {});```

## ./static/src/components/floating_bar/floating_bar.scss
```scss
.shopping-cart-floating-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(135deg, #714B67 0%, #017E84 100%);
    color: white;
    padding: 16px 24px;
    box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.15);
    z-index: 999;
    animation: slideUp 0.3s ease-out;
}

@keyframes slideUp {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
}

.floating-bar-content {
    max-width: 1600px;
    margin: 0 auto;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
}

.cart-summary {
    font-size: 16px;
    font-weight: 500;
}

.cart-actions {
    display: flex;
    gap: 8px;
}

.cart-checkbox {
    width: 20px;
    height: 20px;
    cursor: pointer;
}

.col-checkbox {
    width: 50px;
}

.product-group {
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 16px;
    background: #fafafa;
}

.product-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 2px solid #714B67;
}

.cart-summary-footer {
    background: #f5f5f5;
    padding: 16px;
    border-radius: 8px;
    text-align: center;
}

.o_inventory_visual_content {
    padding-bottom: 120px;
}```

## ./static/src/components/floating_bar/floating_bar.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    
    <t t-name="inventory_shopping_cart.FloatingBar" owl="1">
        <div class="shopping-cart-floating-bar" t-if="cart.totalLots > 0">
            <div class="floating-bar-content">
                <div class="cart-summary">
                    <i class="fa fa-shopping-cart me-2"></i>
                    <strong t-esc="Object.keys(cart.productGroups).length"></strong> <t t-if="Object.keys(cart.productGroups).length === 1">Modelo</t><t t-else="">Modelos</t> |
                    <strong t-esc="cart.totalLots"></strong> <t t-if="cart.totalLots === 1">Unidad</t><t t-else="">Unidades</t> |
                    <strong t-esc="formatNumber(cart.totalQuantity)"></strong> m²
                </div>
                <div class="cart-actions">
                    <button class="btn btn-sm btn-light me-2" t-on-click="clearCart">
                        <i class="fa fa-times"></i> Limpiar
                    </button>
                    <button class="btn btn-sm btn-primary" t-on-click="openCartDialog">
                        <i class="fa fa-shopping-cart"></i> Ver Carrito
                    </button>
                </div>
            </div>
        </div>
    </t>
    
    <t t-name="inventory_visual_enhanced.InventoryView" t-inherit="inventory_visual_enhanced.InventoryView" t-inherit-mode="extension" owl="1">
        <xpath expr="//div[hasclass('o_inventory_visual_content')]" position="after">
            <t t-call="inventory_shopping_cart.FloatingBar"/>
        </xpath>
        <xpath expr="//div[hasclass('o_inventory_visual_content')]" position="attributes">
            <attribute name="style">padding-bottom: 120px;</attribute>
        </xpath>
    </t>
    
</templates>```

## ./static/src/patches/inventory_controller_patch.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    
    <t t-name="inventory_visual_enhanced.InventoryView" t-inherit="inventory_visual_enhanced.InventoryView" t-inherit-mode="extension" owl="1">
        <xpath expr="//ProductRow" position="attributes">
            <attribute name="isInCart.bind">isInCart</attribute>
            <attribute name="toggleCartSelection.bind">toggleCartSelection</attribute>
            <attribute name="areAllCurrentProductSelected.bind">areAllCurrentProductSelected</attribute>
            <attribute name="selectAllCurrentProduct.bind">selectAllCurrentProduct</attribute>
            <attribute name="deselectAllCurrentProduct.bind">deselectAllCurrentProduct</attribute>
            <attribute name="cart">cart</attribute>
        </xpath>
    </t>
    
    <t t-name="inventory_visual_enhanced.ProductDetails" t-inherit="inventory_visual_enhanced.ProductDetails" t-inherit-mode="extension" owl="1">
        <!-- Reemplazar el header del checkbox con seleccionar todo -->
        <xpath expr="//thead/tr/th[@class='col-checkbox']" position="replace">
            <th class="col-checkbox text-center" style="width: 50px;">
                <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
                    <input 
                        type="checkbox" 
                        class="cart-checkbox-all" 
                        t-att-checked="props.areAllCurrentProductSelected ? (props.areAllCurrentProductSelected() ? 'checked' : undefined) : undefined"
                        t-on-click.stop="() => props.areAllCurrentProductSelected() ? props.deselectAllCurrentProduct() : props.selectAllCurrentProduct()"
                        title="Seleccionar/Deseleccionar todos los lotes de este producto"
                    />
                    <small style="font-size: 10px; color: #666;">Todo</small>
                </div>
            </th>
        </xpath>
        
        <!-- Modificar el checkbox individual en el body -->
        <xpath expr="//td[@class='col-checkbox text-center']" position="replace">
            <td class="col-checkbox text-center">
                <input 
                    type="checkbox"
                    class="form-check-input cart-checkbox"
                    t-att-checked="props.isInCart ? (props.isInCart(detail.id) ? 'checked' : undefined) : undefined"
                    t-on-click.stop="() => props.toggleCartSelection ? props.toggleCartSelection(detail) : null"
                />
            </td>
        </xpath>
    </t>
    
</templates>```

## ./views/product_template_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="product_template_form_view_custom_prices" model="ir.ui.view">
        <field name="name">product.template.form.custom.prices</field>
        <field name="model">product.template</field>
        <field name="inherit_id" ref="product.product_template_only_form_view"/>
        <field name="arch" type="xml">
            <xpath expr="//page[@name='sales']" position="after">
                <page string="Precios Personalizados" name="custom_prices">
                    <group>
                        <group string="Precios USD">
                            <field name="x_price_usd_1"/>
                            <field name="x_price_usd_2"/>
                            <field name="x_price_usd_3"/>
                        </group>
                        <group string="Precios MXN">
                            <field name="x_price_mxn_1"/>
                            <field name="x_price_mxn_2"/>
                            <field name="x_price_mxn_3"/>
                        </group>
                    </group>
                </page>
            </xpath>
        </field>
    </record>
</odoo>```

