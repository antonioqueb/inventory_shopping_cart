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
        
        // Estado para almacenar valores escritos en los inputs que AÚN NO están en el carrito
        // o para persistir el valor mientras se edita
        this.state.manualInputValues = {}; 
        
        this.cart = useState({
            items: [],
            totalQuantity: 0,
            totalLots: 0,
            typeLabel: 'Placas', // Default
            productGroups: {},
            hasSalesPermissions: false,
            hasInventoryPermissions: false
        });
        
        this.isInCart = this.isInCart.bind(this);
        this.getDisplayQuantity = this.getDisplayQuantity.bind(this);
        this.toggleCartSelection = this.toggleCartSelection.bind(this);
        this.onInputManualQuantity = this.onInputManualQuantity.bind(this);
        this.selectAllCurrentProduct = this.selectAllCurrentProduct.bind(this);
        this.deselectAllCurrentProduct = this.deselectAllCurrentProduct.bind(this);
        this.areAllCurrentProductSelected = this.areAllCurrentProductSelected.bind(this);
        
        this.loadCartFromDB();
        this.loadSalesPermissions();
        this.loadInventoryPermissions();
    },

    async loadSalesPermissions() {
        try {
            const result = await this.orm.call('stock.quant', 'check_sales_permissions', []);
            this.cart.hasSalesPermissions = result;
        } catch (error) {
            console.error('[CART] Error verificando permisos:', error);
            this.cart.hasSalesPermissions = false;
        }
    },
    
    async loadInventoryPermissions() {
        try {
            const result = await this.orm.call('stock.quant', 'check_inventory_permissions', []);
            this.cart.hasInventoryPermissions = result;
        } catch (error) {
            console.error('[CART] Error verificando permisos de inventario:', error);
            this.cart.hasInventoryPermissions = false;
        }
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

    /**
     * Devuelve el valor a mostrar en el input.
     * Prioridad 1: Si está en carrito, muestra cantidad del carrito.
     * Prioridad 2: Si hay valor manual temporal, muestra ese.
     * Prioridad 3: Vacío.
     */
    getDisplayQuantity(detailId) {
        const cartItem = this.cart.items.find(item => item.id === detailId);
        if (cartItem) {
            return cartItem.quantity;
        }
        return this.state.manualInputValues[detailId] || '';
    },
    
    /**
     * Lógica al hacer click en el Checkbox.
     * - Si está marcado: Lo quita.
     * - Si está desmarcado: Lo agrega.
     *   -> Si hay valor en input manual: Usa ese valor.
     *   -> Si input está vacío: Usa TODO el lote.
     */
    async toggleCartSelection(detail) {
        const index = this.cart.items.findIndex(item => item.id === detail.id);
        
        if (index >= 0) {
            // ESTABA MARCADO -> DESMARCAR (Eliminar)
            this.cart.items.splice(index, 1);
            await this.orm.call('shopping.cart', 'remove_from_cart', [detail.id]);
        } else {
            // ESTABA DESMARCADO -> MARCAR (Agregar)
            
            // Verificar si hay un valor manual escrito
            let manualQty = parseFloat(this.state.manualInputValues[detail.id]);
            
            // Lógica de negocio: Si input vacío o 0 -> Agarra todo el lote. Si tiene valor -> Agarra valor.
            let finalQty = (manualQty && manualQty > 0) ? manualQty : detail.quantity;
            
            // Validar tope máximo (opcional)
            if (finalQty > detail.quantity) {
                finalQty = detail.quantity;
                this.notification.add(`Cantidad ajustada al máximo disponible (${finalQty} m²)`, { type: "info" });
            }

            await this.addOrUpdateCartItem(detail, finalQty);
        }
        
        this.updateCartSummary();
        this.cart.items = [...this.cart.items]; // Reactividad
    },

    /**
     * Lógica al escribir en el Input numérico.
     */
    async onInputManualQuantity(detail, value) {
        const qty = parseFloat(value);
        
        // Guardamos el valor temporal siempre
        if (isNaN(qty) || qty === 0) {
            delete this.state.manualInputValues[detail.id];
        } else {
            this.state.manualInputValues[detail.id] = qty;
        }

        // Si el item YA está en el carrito, actualizamos en tiempo real
        if (this.isInCart(detail.id)) {
            // Si el usuario borra el input estando chequeado, volvemos a la cantidad total del lote
            let finalQty = (qty && qty > 0) ? qty : detail.quantity;
            
            if (finalQty > detail.quantity) {
                finalQty = detail.quantity;
                // No mostrar notificación intrusiva mientras escribe, pero ajustar silenciosamente
            }
            
            await this.addOrUpdateCartItem(detail, finalQty);
            this.updateCartSummary();
            this.cart.items = [...this.cart.items];
        }
    },

    async addOrUpdateCartItem(detail, quantity) {
        const index = this.cart.items.findIndex(item => item.id === detail.id);
        
        if (index >= 0) {
            // Actualizar local
            this.cart.items[index].quantity = quantity;
        } else {
            // Agregar nuevo local
            this.cart.items.push({
                id: detail.id,
                lot_id: detail.lot_id,
                lot_name: detail.lot_name,
                product_id: this.getCurrentProductId(detail),
                product_name: this.getCurrentProductName(detail),
                quantity: quantity,
                location_name: detail.location_name,
                tiene_hold: detail.tiene_hold,
                hold_info: detail.hold_info,
                seller_name: detail.seller_name || '',
                product_type: detail.tipo || 'placa'
            });
        }

        try {
            await this.orm.call('shopping.cart', 'add_to_cart', [], {
                quant_id: detail.id,
                lot_id: detail.lot_id,
                product_id: this.getCurrentProductId(detail),
                quantity: quantity,
                location_name: detail.location_name
            });
        } catch (error) {
            console.error('[CART] Error agregando/actualizando en carrito:', error);
            // Revertir si es nuevo y falló
            if (index < 0) this.cart.items.pop(); 
            this.notification.add("Error al actualizar el carrito", { type: "danger" });
        }
    },
    
    async selectAllCurrentProduct() {
        if (!this.state.activeProductId) return;
        const details = this.getProductDetails(this.state.activeProductId);
        for (const detail of details) {
            if (!this.isInCart(detail.id)) {
                await this.toggleCartSelection(detail);
            }
        }
        this._forceRenderProduct(this.state.activeProductId);
    },
    
    async deselectAllCurrentProduct() {
        if (!this.state.activeProductId) return;
        const details = this.getProductDetails(this.state.activeProductId);
        for (const detail of details) {
            if (this.isInCart(detail.id)) {
                await this.toggleCartSelection(detail);
            }
        }
        this._forceRenderProduct(this.state.activeProductId);
    },

    async _forceRenderProduct(productId) {
        const product = this.state.products.find(p => p.product_id === productId);
        if (product) {
            this.state.expandedProducts.delete(productId);
            this.state.expandedProducts = new Set(this.state.expandedProducts);
            await new Promise(resolve => setTimeout(resolve, 50));
            this.state.expandedProducts.add(productId);
            await this.loadProductDetails(productId, product.quant_ids);
            this.state.expandedProducts = new Set(this.state.expandedProducts);
        }
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
        
        // === CÁLCULO DE ETIQUETA DINÁMICA ===
        const uniqueTypes = new Set(this.cart.items.map(item => (item.product_type || 'placa').toLowerCase()));
        
        if (uniqueTypes.size === 0) {
            this.cart.typeLabel = 'Items';
        } else if (uniqueTypes.size > 1) {
            // Si hay mezcla de tipos, usamos "Unidades"
            this.cart.typeLabel = 'Unidades';
        } else {
            // Solo hay un tipo, usamos ese
            const type = [...uniqueTypes][0];
            const isPlural = this.cart.totalLots !== 1;
            
            if (type === 'formato') {
                this.cart.typeLabel = isPlural ? 'Formatos' : 'Formato';
            } else if (type === 'pieza') {
                this.cart.typeLabel = isPlural ? 'Piezas' : 'Pieza';
            } else {
                this.cart.typeLabel = isPlural ? 'Placas' : 'Placa';
            }
        }
        // =====================================

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
        
        // OBTENER TODOS LOS PRODUCTOS QUE ESTÁN EXPANDIDOS
        const expandedProductIds = Array.from(this.state.expandedProducts);
        
        if (expandedProductIds.length > 0) {
            // COLAPSAR TODOS LOS PRODUCTOS EXPANDIDOS
            this.state.expandedProducts.clear();
            this.state.expandedProducts = new Set(this.state.expandedProducts);
            
            // Pequeño delay para que el DOM se actualice
            await new Promise(resolve => setTimeout(resolve, 50));
            
            // RE-EXPANDIR TODOS LOS PRODUCTOS QUE ESTABAN EXPANDIDOS
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
        
        // Forzar actualización reactiva
        this.cart.items = [...this.cart.items];
        
        this.notification.add("Lotes apartados eliminados del carrito", { type: "success" });
        
        // OBTENER TODOS LOS PRODUCTOS QUE ESTÁN EXPANDIDOS
        const expandedProductIds = Array.from(this.state.expandedProducts);
        
        if (expandedProductIds.length > 0) {
            // COLAPSAR TODOS LOS PRODUCTOS EXPANDIDOS
            this.state.expandedProducts.clear();
            this.state.expandedProducts = new Set(this.state.expandedProducts);
            
            await new Promise(resolve => setTimeout(resolve, 50));
            
            // RE-EXPANDIR TODOS LOS PRODUCTOS QUE ESTABAN EXPANDIDOS
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
});