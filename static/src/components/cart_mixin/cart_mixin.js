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
        
        // ✅ FORZAR RE-RENDERIZACIÓN de los detalles del producto activo
        if (this.state.activeProductId && this.state.expandedProducts.has(this.state.activeProductId)) {
            const productId = this.state.activeProductId;
            const quantIds = this.state.products.find(p => p.product_id === productId)?.quant_ids || [];
            
            // Colapsar y expandir para forzar re-render
            this.state.expandedProducts.delete(productId);
            this.state.expandedProducts = new Set(this.state.expandedProducts);
            
            // Pequeño delay para que el DOM se actualice
            await new Promise(resolve => setTimeout(resolve, 50));
            
            this.state.expandedProducts.add(productId);
            await this.loadProductDetails(productId, quantIds);
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
        
        // ✅ FORZAR RE-RENDERIZACIÓN si hay producto activo expandido
        if (this.state.activeProductId && this.state.expandedProducts.has(this.state.activeProductId)) {
            const productId = this.state.activeProductId;
            const quantIds = this.state.products.find(p => p.product_id === productId)?.quant_ids || [];
            
            this.state.expandedProducts.delete(productId);
            this.state.expandedProducts = new Set(this.state.expandedProducts);
            
            await new Promise(resolve => setTimeout(resolve, 50));
            
            this.state.expandedProducts.add(productId);
            await this.loadProductDetails(productId, quantIds);
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
});