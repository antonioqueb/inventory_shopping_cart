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
        // ✅ VALIDACIÓN DE PERMISOS
        if (!this.cart.hasSalesPermissions) {
            this.props.close();
            return;
        }
        this.props.close();
        this.props.onCreateHolds();
    }
    
    createSaleOrder() {
        // ✅ VALIDACIÓN DE PERMISOS
        if (!this.cart.hasSalesPermissions) {
            this.props.close();
            return;
        }
        this.props.close();
        this.props.onCreateSaleOrder();
    }
    
    createTransfer() {
        // ✅ VALIDACIÓN DE PERMISOS
        if (!this.cart.hasInventoryPermissions) {
            this.props.close();
            return;
        }
        this.props.close();
        this.props.onCreateTransfer();
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
    onCreateTransfer: Function,
};