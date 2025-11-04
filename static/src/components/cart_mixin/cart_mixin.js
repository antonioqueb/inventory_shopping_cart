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
});