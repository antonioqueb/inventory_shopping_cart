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
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Sistema de carrito de compra y apartado múltiple desde inventario visual',
    'author': 'Alphaqueb Consulting SAS',
    'website': 'https://alphaqueb.com',
    'depends': ['inventory_visual_enhanced', 'stock_lot_dimensions', 'sale'],
    'data': [
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
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}```

## ./models/__init__.py
```py
# -*- coding: utf-8 -*-
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
# ./models/sale_order.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    x_selected_lots = fields.Many2many('stock.quant', string='Lotes Seleccionados')

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    @api.model
    def create_from_shopping_cart(self, partner_id=None, products=None, notes=None, pricelist_id=None, apply_tax=True):
        if not partner_id or not products:
            raise UserError("Faltan parámetros: partner_id o products")
        
        if not pricelist_id:
            raise UserError("Debe especificar una lista de precios")
        
        for product in products:
            for quant_id in product['selected_lots']:
                quant = self.env['stock.quant'].browse(quant_id)
                if quant.x_tiene_hold:
                    hold_partner = quant.x_hold_activo_id.partner_id
                    if hold_partner.id != partner_id:
                        raise UserError(f"El lote {quant.lot_id.name} está apartado para {hold_partner.name}")
        
        sale_order = self.env['sale.order'].create({
            'partner_id': partner_id,
            'note': notes or '',
            'pricelist_id': pricelist_id,
        })
        
        for product in products:
            product_rec = self.env['product.product'].browse(product['product_id'])
            
            if apply_tax and product_rec.taxes_id:
                tax_ids = [(6, 0, product_rec.taxes_id.ids)]
            else:
                tax_ids = [(5, 0, 0)]
            
            self.env['sale.order.line'].create({
                'order_id': sale_order.id,
                'product_id': product['product_id'],
                'product_uom_qty': product['quantity'],
                'price_unit': product['price_unit'],
                'tax_id': tax_ids,
                'x_selected_lots': [(6, 0, product['selected_lots'])]
            })
        
        sale_order.action_confirm()
        
        for line in sale_order.order_line:
            if line.x_selected_lots:
                picking = line.move_ids.mapped('picking_id')
                if picking:
                    self._assign_specific_lots(picking, line.product_id, line.x_selected_lots)
        
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

## ./models/stock_quant.py
```py
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
        
        console.log('[CART] 🚀 Inicializando cart system');
        
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
        
        console.log('[CART] ✅ Cart inicializado con useState:', this.cart);
        
        this.isInCart = this.isInCart.bind(this);
        this.toggleCartSelection = this.toggleCartSelection.bind(this);
        this.selectAllCurrentProduct = this.selectAllCurrentProduct.bind(this);
        this.deselectAllCurrentProduct = this.deselectAllCurrentProduct.bind(this);
        this.areAllCurrentProductSelected = this.areAllCurrentProductSelected.bind(this);
    },
    
    async toggleProduct(productId, quantIds) {
        console.log('[CART] 📦 toggleProduct llamado:', { productId, quantIds });
        
        const isExpanded = this.state.expandedProducts.has(productId);

        this.state.activeProductId = productId;
        const product = this.state.products.find(p => p.product_id === productId);
        this.state.activeProductName = product ? product.product_name : '';
        
        console.log('[CART] 🎯 Producto activo actualizado:', {
            activeProductId: this.state.activeProductId,
            activeProductName: this.state.activeProductName
        });

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
        const inCart = this.cart.items.some(item => item.id === detailId);
        console.log('[CART] 🔍 isInCart:', { detailId, inCart, totalItems: this.cart.items.length });
        return inCart;
    },
    
    toggleCartSelection(detail) {
        console.log('[CART] 🔄 toggleCartSelection llamado:', detail);
        
        const index = this.cart.items.findIndex(item => item.id === detail.id);
        
        if (index >= 0) {
            console.log('[CART] ➖ Removiendo del carrito:', { id: detail.id, index });
            this.cart.items.splice(index, 1);
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
                hold_info: detail.hold_info
            };
            console.log('[CART] ➕ Agregando al carrito:', newItem);
            this.cart.items.push(newItem);
        }
        
        console.log('[CART] 📊 Estado del carrito después de toggle:', {
            totalItems: this.cart.items.length,
            items: this.cart.items.map(i => ({ id: i.id, lot: i.lot_name }))
        });
        
        this.updateCartSummary();
    },
    
    selectAllCurrentProduct() {
        console.log('[CART] ✅ selectAllCurrentProduct llamado');
        console.log('[CART] 🎯 Producto activo:', {
            activeProductId: this.state.activeProductId,
            activeProductName: this.state.activeProductName
        });
        
        if (!this.state.activeProductId) {
            console.warn('[CART] ⚠️ No hay producto activo, abortando');
            return;
        }
        
        const details = this.getProductDetails(this.state.activeProductId);
        console.log('[CART] 📋 Detalles obtenidos:', {
            totalDetails: details.length,
            details: details.map(d => ({ id: d.id, lot: d.lot_name }))
        });
        
        let added = 0;
        details.forEach(detail => {
            const alreadyInCart = this.isInCart(detail.id);
            console.log('[CART] 🔍 Evaluando detalle:', {
                id: detail.id,
                lot: detail.lot_name,
                alreadyInCart
            });
            
            if (!alreadyInCart) {
                console.log('[CART] ➕ Agregando al carrito vía toggle:', detail.id);
                this.toggleCartSelection(detail);
                added++;
            } else {
                console.log('[CART] ⏭️ Ya está en carrito, saltando:', detail.id);
            }
        });
        
        console.log('[CART] ✅ selectAllCurrentProduct finalizado:', {
            added,
            totalInCart: this.cart.items.length
        });
    },
    
    deselectAllCurrentProduct() {
        console.log('[CART] ❌ deselectAllCurrentProduct llamado');
        console.log('[CART] 🎯 Producto activo:', {
            activeProductId: this.state.activeProductId,
            activeProductName: this.state.activeProductName
        });
        
        if (!this.state.activeProductId) {
            console.warn('[CART] ⚠️ No hay producto activo, abortando');
            return;
        }
        
        const details = this.getProductDetails(this.state.activeProductId);
        console.log('[CART] 📋 Detalles obtenidos para deselección:', {
            totalDetails: details.length,
            details: details.map(d => ({ id: d.id, lot: d.lot_name }))
        });
        
        let removed = 0;
        details.forEach(detail => {
            const inCart = this.isInCart(detail.id);
            console.log('[CART] 🔍 Evaluando detalle para remover:', {
                id: detail.id,
                lot: detail.lot_name,
                inCart
            });
            
            if (inCart) {
                console.log('[CART] ➖ Removiendo del carrito vía toggle:', detail.id);
                this.toggleCartSelection(detail);
                removed++;
            } else {
                console.log('[CART] ⏭️ No está en carrito, saltando:', detail.id);
            }
        });
        
        console.log('[CART] ✅ deselectAllCurrentProduct finalizado:', {
            removed,
            totalInCart: this.cart.items.length
        });
    },
    
    areAllCurrentProductSelected() {
        console.log('[CART] 🔍 areAllCurrentProductSelected llamado');
        
        if (!this.state.activeProductId) {
            console.warn('[CART] ⚠️ No hay producto activo, retornando false');
            return false;
        }
        
        const details = this.getProductDetails(this.state.activeProductId);
        if (details.length === 0) {
            console.warn('[CART] ⚠️ No hay detalles, retornando false');
            return false;
        }
        
        const allSelected = details.every(detail => this.isInCart(detail.id));
        
        console.log('[CART] 📊 Resultado de verificación:', {
            totalDetails: details.length,
            allSelected,
            selectedCount: details.filter(d => this.isInCart(d.id)).length,
            details: details.map(d => ({ id: d.id, lot: d.lot_name, inCart: this.isInCart(d.id) }))
        });
        
        return allSelected;
    },
    
    getCurrentProductId(detail) {
        for (const product of this.state.products) {
            const details = this.getProductDetails(product.product_id);
            if (details.find(d => d.id === detail.id)) {
                return product.product_id;
            }
        }
        console.warn('[CART] ⚠️ No se encontró product_id para detail:', detail.id);
        return null;
    },
    
    getCurrentProductName(detail) {
        for (const product of this.state.products) {
            const details = this.getProductDetails(product.product_id);
            if (details.find(d => d.id === detail.id)) {
                return product.product_name;
            }
        }
        console.warn('[CART] ⚠️ No se encontró product_name para detail:', detail.id);
        return '';
    },
    
    updateCartSummary() {
        console.log('[CART] 📊 updateCartSummary llamado');
        
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
        
        console.log('[CART] 📊 Resumen actualizado:', {
            totalLots: this.cart.totalLots,
            totalQuantity: this.cart.totalQuantity,
            productGroups: Object.keys(groups).length
        });
    },
    
    clearCart() {
        console.log('[CART] 🗑️ clearCart llamado');
        this.cart.items = [];
        this.updateCartSummary();
        console.log('[CART] ✅ Carrito limpiado');
    },
    
    removeLotsWithHold() {
        console.log('[CART] 🔒 removeLotsWithHold llamado');
        const before = this.cart.items.length;
        this.cart.items = this.cart.items.filter(item => !item.tiene_hold);
        const after = this.cart.items.length;
        this.updateCartSummary();
        console.log('[CART] ✅ Lotes con hold removidos:', { before, after, removed: before - after });
        this.notification.add("Lotes apartados eliminados del carrito", { type: "success" });
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
                            <span class="badge bg-secondary "><t t-esc="formatNumber(group.total_quantity)"/> m²</span>
                        </div>
                        
                        <table class="table table-sm">
                            <tbody>
                                <t t-foreach="group.lots" t-as="lot" t-key="lot.id">
                                    <tr>
                                        <td><t t-esc="lot.lot_name"/></td>
                                        <td><t t-esc="formatNumber(lot.quantity)"/> m²</td>
                                        <td><t t-esc="lot.location_name"/></td>
                                        <td>
                                            <span t-if="lot.tiene_hold" class="badge bg-warning">🔒 Apartado</span>
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
            
            // Notas
            notas: '',
            
            // UI
            isCreating: false,
            currentStep: 1, // 1: Cliente, 2: Proyecto, 3: Arquitecto, 4: Confirmar
        });
        
        this.searchTimeout = null;
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
        
        if (this.state.currentStep < 4) {
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
                    notes: this.state.notas
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
}

HoldWizard.template = "inventory_shopping_cart.HoldWizard";
HoldWizard.components = { Dialog };
HoldWizard.props = {
    close: Function,
    selectedLots: Array,
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
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 4 }">
                            <div class="step-number">4</div>
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
                    
                    <!-- Toggle: Seleccionar o Crear -->
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
                    
                    <!-- Buscar cliente existente -->
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
                        
                        <!-- Cliente seleccionado -->
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedPartnerName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Cliente seleccionado:</strong><br/>
                                <t t-esc="state.selectedPartnerName"/>
                            </div>
                        </div>
                        
                        <!-- Lista de resultados -->
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
                    
                    <!-- Crear nuevo cliente -->
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
                    
                    <!-- Toggle: Seleccionar o Crear -->
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
                    
                    <!-- Buscar proyecto existente -->
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
                        
                        <!-- Proyecto seleccionado -->
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedProjectName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Proyecto seleccionado:</strong><br/>
                                <t t-esc="state.selectedProjectName"/>
                            </div>
                        </div>
                        
                        <!-- Lista de resultados -->
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
                    
                    <!-- Crear nuevo proyecto -->
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
                    
                    <!-- Toggle: Seleccionar o Crear -->
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
                    
                    <!-- Buscar arquitecto existente -->
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
                        
                        <!-- Arquitecto seleccionado -->
                        <div class="alert alert-light border d-flex align-items-center mb-3" t-if="state.selectedArchitectName">
                            <i class="fa fa-check-circle fa-2x text-success me-3"></i>
                            <div>
                                <strong>Arquitecto seleccionado:</strong><br/>
                                <t t-esc="state.selectedArchitectName"/>
                            </div>
                        </div>
                        
                        <!-- Lista de resultados -->
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
                    
                    <!-- Crear nuevo arquitecto -->
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
                
                <!-- PASO 4: CONFIRMAR -->
                <div class="step-content" t-if="state.currentStep === 4">
                    <h5 class="mb-3">
                        <i class="fa fa-check-circle text-success me-2"></i>
                        Confirmar Apartados
                    </h5>
                    
                    <!-- Resumen -->
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
                                    <strong>Total de lotes:</strong><br/>
                                    <t t-esc="props.selectedLots.length"/>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Notas -->
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
                    
                    <!-- Info de expiración -->
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
                <!-- Botones de navegación -->
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="prevStep"
                    t-if="state.currentStep > 1 and state.currentStep &lt; 4"
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
                    t-if="state.currentStep &lt; 4"
                >
                    Siguiente
                    <i class="fa fa-chevron-right ms-2"></i>
                </button>
                
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="prevStep"
                    t-if="state.currentStep === 4"
                >
                    <i class="fa fa-chevron-left me-2"></i>
                    Anterior
                </button>
                
                <button 
                    class="btn btn-primary btn-lg"
                    t-on-click="createHolds"
                    t-if="state.currentStep === 4"
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
// ./static/src/components/dialogs/sale_order_wizard/sale_order_wizard.js
/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class SaleOrderWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        
        this.state = useState({
            searchPartnerTerm: '',
            partners: [],
            selectedPartnerId: null,
            selectedPartnerName: '',
            showCreatePartner: false,
            newPartnerName: '',
            newPartnerVat: '',
            newPartnerRef: '',
            
            selectedCurrency: 'USD',
            pricelists: [],
            selectedPricelistId: null,
            
            productPrices: {},
            productPriceOptions: {},
            
            notas: '',
            applyTax: true,
            
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
            
            await this.loadProductPrices();
        } catch (error) {
            this.notification.add("Error al cargar listas de precios", { type: "warning" });
        }
    }
    
    async loadProductPrices() {
        try {
            for (const [productId, group] of Object.entries(this.props.productGroups)) {
                const prices = await this.orm.call(
                    "product.template",
                    "get_custom_prices",
                    [],
                    {
                        product_id: parseInt(productId),
                        currency_code: this.state.selectedCurrency
                    }
                );
                
                this.state.productPriceOptions[productId] = prices;
                
                if (prices.length > 0) {
                    this.state.productPrices[productId] = prices[0].value;
                }
            }
        } catch (error) {
            this.notification.add("Error al cargar precios", { type: "danger" });
        }
    }
    
    async onCurrencyChange(ev) {
        const pricelistName = ev.target.value;
        this.state.selectedCurrency = pricelistName;
        
        const pricelist = this.state.pricelists.find(p => p.name === pricelistName);
        if (pricelist) {
            this.state.selectedPricelistId = pricelist.id;
        }
        
        await this.loadProductPrices();
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
            this.notification.add("Error al crear cliente", { type: "danger" });
        }
    }
    
    nextStep() {
        if (this.state.currentStep === 1 && !this.state.selectedPartnerId) {
            this.notification.add("Debe seleccionar o crear un cliente", { type: "warning" });
            return;
        }
        
        if (this.state.currentStep === 2) {
            const hasInvalidPrice = Object.entries(this.state.productPrices).some(([pid, price]) => {
                const options = this.state.productPriceOptions[pid] || [];
                if (options.length === 0) return price <= 0;
                const minPrice = Math.min(...options.map(opt => opt.value));
                return price < minPrice;
            });
            
            if (hasInvalidPrice) {
                this.notification.add("Hay precios inválidos", { type: "warning" });
                return;
            }
        }
        
        if (this.state.currentStep < 3) {
            this.state.currentStep++;
        }
    }
    
    prevStep() {
        if (this.state.currentStep > 1) {
            this.state.currentStep--;
        }
    }
    
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
            
            let finalNotes = this.state.notas || '';
            if (!this.state.applyTax) {
                finalNotes += '\n\n⚠️ NOTA IMPORTANTE: El IVA se agregará posteriormente por cuestiones legales.';
            }
            
            const result = await this.orm.call("sale.order", "create_from_shopping_cart", [], {
                partner_id: this.state.selectedPartnerId,
                products: products,
                notes: finalNotes,
                pricelist_id: this.state.selectedPricelistId,
                apply_tax: this.state.applyTax
            });
            
            if (result.success) {
                this.notification.add(`Orden ${result.order_name} creada exitosamente`, { type: "success" });
                this.props.onSuccess();
                this.props.close();
            }
        } catch (error) {
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
        <Dialog size="'lg'">
            <div class="sale-order-wizard-content">
                <div class="alert alert-light border-start border-4 border-primary mb-4">
                    <div class="d-flex align-items-center">
                        <i class="fa fa-file-text fa-2x text-primary me-3"></i>
                        <div>
                            <h5 class="mb-1 fw-bold">Crear Orden de Venta</h5>
                            <small class="text-muted">
                                <i class="fa fa-cubes me-1"></i>
                                <strong t-esc="Object.keys(props.productGroups).length"></strong> productos
                            </small>
                        </div>
                    </div>
                </div>
                
                <div class="steps-indicator mb-4">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 1, completed: state.currentStep > 1 }">
                            <div class="step-number">1</div>
                            <div class="step-label">Cliente</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 1 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 2, completed: state.currentStep > 2 }">
                            <div class="step-number">2</div>
                            <div class="step-label">Precios</div>
                        </div>
                        <div class="step-line" t-att-class="{ active: state.currentStep > 2 }"></div>
                        <div class="step-item" t-att-class="{ active: state.currentStep >= 3 }">
                            <div class="step-number">3</div>
                            <div class="step-label">Confirmar</div>
                        </div>
                    </div>
                </div>
                
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
                
                <div class="step-content" t-if="state.currentStep === 2">
                    <h5 class="mb-3">
                        <i class="fa fa-dollar text-primary me-2"></i>
                        Configurar Precios
                    </h5>
                    
                    <div class="mb-4">
                        <label class="form-label fw-bold">Divisa / Lista de Precios *</label>
                        <select class="form-select form-select-lg" t-model="state.selectedCurrency" t-on-change="onCurrencyChange">
                            <option value="USD">USD - Dólares</option>
                            <option value="MXN">MXN - Pesos</option>
                        </select>
                    </div>
                    
                    <div class="mb-3">
                        <label class="form-label fw-bold">Precios por Producto</label>
                        <t t-foreach="Object.entries(props.productGroups)" t-as="entry" t-key="entry[0]">
                            <t t-set="productId" t-value="entry[0]"/>
                            <t t-set="group" t-value="entry[1]"/>
                            
                            <div class="card mb-3 border">
                                <div class="card-body">
                                    <div class="row align-items-center">
                                        <div class="col-md-5">
                                            <strong t-esc="group.name"></strong><br/>
                                            <small class="text-muted">
                                                <i class="fa fa-cube me-1"></i>
                                                <t t-esc="formatNumber(group.total_quantity)"/> m²
                                            </small>
                                        </div>
                                        <div class="col-md-4">
                                            <t t-if="state.productPriceOptions[productId] and state.productPriceOptions[productId].length > 0">
                                                <select 
                                                    class="form-select"
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
                                            <t t-else="">
                                                <div class="alert alert-danger mb-0 p-2">
                                                    <small>Sin precios configurados</small>
                                                </div>
                                            </t>
                                        </div>
                                        <div class="col-md-3">
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
                            </div>
                        </t>
                    </div>
                    
                    <div class="row">
                        <div class="col-md-12">
                            <label class="form-label fw-bold">IVA</label>
                            <div class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" role="switch" t-model="state.applyTax" id="applyTaxSwitch"/>
                                <label class="form-check-label" for="applyTaxSwitch">
                                    <t t-if="state.applyTax">Aplicar IVA</t>
                                    <t t-else="">Sin IVA (se agregará nota legal)</t>
                                </label>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="step-content" t-if="state.currentStep === 3">
                    <h5 class="mb-3">
                        <i class="fa fa-check-circle text-success me-2"></i>
                        Confirmar Orden
                    </h5>
                    
                    <div class="card border mb-3">
                        <div class="card-body">
                            <h6 class="card-title mb-3">Resumen</h6>
                            
                            <div class="row g-3 mb-3">
                                <div class="col-md-6">
                                    <strong>Cliente:</strong><br/>
                                    <t t-esc="state.selectedPartnerName"/>
                                </div>
                                <div class="col-md-6">
                                    <strong>Divisa:</strong><br/>
                                    <t t-esc="state.selectedCurrency"/>
                                </div>
                            </div>
                            
                            <table class="table table-sm">
                                <thead>
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
                            </table>
                        </div>
                    </div>
                    
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
                    t-if="state.currentStep > 1 and state.currentStep &lt; 3"
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
                    t-if="state.currentStep &lt; 3"
                >
                    Siguiente
                    <i class="fa fa-chevron-right ms-2"></i>
                </button>
                
                <button 
                    class="btn btn-light border btn-lg"
                    t-on-click="prevStep"
                    t-if="state.currentStep === 3"
                >
                    <i class="fa fa-chevron-left me-2"></i>
                    Anterior
                </button>
                
                <button 
                    class="btn btn-success btn-lg"
                    t-on-click="createSaleOrder"
                    t-if="state.currentStep === 3"
                    t-att-disabled="state.isCreating"
                >
                    <t t-if="!state.isCreating">
                        <i class="fa fa-check me-2"></i>
                        Crear Orden
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
// inventory_shopping_cart/static/src/components/floating_bar/floating_bar.js
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { CartDialog } from "../dialogs/cart_dialog/cart_dialog";
import { HoldWizard } from "../dialogs/hold_wizard/hold_wizard";
import { SaleOrderWizard } from "../dialogs/sale_order_wizard/sale_order_wizard";

const InventoryVisualController = registry.category("actions").get("inventory_visual_enhanced");

patch(InventoryVisualController.prototype, {
    openCartDialog() {
        if (this.cart.totalLots === 0) {
            this.notification.add("El carrito está vacío", { type: "warning" });
            return;
        }
        
        this.dialog.add(CartDialog, {
            cart: this.cart,
            onRemoveHolds: () => this.removeLotsWithHold(),
            onCreateHolds: () => this.openHoldWizard(),
            onCreateSaleOrder: () => this.openSaleOrderWizard()
        });
    },
    
    openHoldWizard() {
        this.dialog.add(HoldWizard, {
            selectedLots: this.cart.items.map(item => item.id),
            onSuccess: async () => {
                this.clearCart();
                await this.searchProducts();
            }
        });
    },
    
    openSaleOrderWizard() {
        const lotsWithHold = this.cart.items.filter(item => item.tiene_hold);
        
        if (lotsWithHold.length > 0) {
            this.notification.add("Hay lotes apartados en el carrito. Use 'Eliminar Apartados' primero.", { type: "warning", sticky: true });
            return;
        }
        
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
                    <strong t-esc="Object.keys(cart.productGroups).length"></strong> <t t-if="Object.keys(cart.productGroups).length === 1">Pieza</t><t t-else="">Piezas</t> |
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
                        t-att-checked="props.areAllCurrentProductSelected()"
                        t-on-click="(ev) => { ev.stopPropagation(); props.areAllCurrentProductSelected() ? props.deselectAllCurrentProduct() : props.selectAllCurrentProduct(); }"
                        title="Seleccionar/Deseleccionar todo"
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
                    t-att-checked="props.isInCart(detail.id)"
                    t-on-click="(ev) => { ev.stopPropagation(); props.toggleCartSelection(detail); }"
                />
            </td>
        </xpath>
    </t>
    
</templates>```

## ./views/product_template_views.xml
```xml
<!-- ./views/product_template_views.xml -->
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

