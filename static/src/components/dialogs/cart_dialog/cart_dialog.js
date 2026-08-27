/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class CartDialog extends Component {
    setup() {
        // Medición SOM: mientras este diálogo esté abierto el tiempo
        // se atribuye a esta pantalla y no a la de atrás. Si el
        // módulo de medición no está instalado, nadie escucha y ya.
        onMounted(() => this.env.bus.trigger("SOM_ACTIVITY:SCREEN",
            { key: "carrito", label: "Carrito" }));
        onWillUnmount(() => this.env.bus.trigger("SOM_ACTIVITY:SCREEN", {}));

        // useState sobre el carrito reactivo del visual: al quitar lotes el
        // diálogo se actualiza en sitio sin cerrarse.
        this.cart = useState(this.props.cart);
        // Selección por lote: la acción (apartar / vender / trasladar /
        // etiquetas) aplica SOLO a lo palomeado — por default todo va
        // seleccionado, el vendedor desmarca lo que no quiere enviar.
        const sel = {};
        for (const item of this.cart.items) {
            sel[item.id] = true;
        }
        this.state = useState({ sel });
    }

    get hasHolds() {
        return this.cart.items.some(item => item.tiene_hold);
    }

    // ── Selección ──
    get selectedIds() {
        return this.cart.items
            .filter((item) => this.state.sel[item.id])
            .map((item) => item.id);
    }

    get selCount() {
        return this.selectedIds.length;
    }

    get selQuantity() {
        return this.cart.items
            .filter((item) => this.state.sel[item.id])
            .reduce((a, item) => a + (item.quantity || 0), 0);
    }

    isSelected(lot) {
        return !!this.state.sel[lot.id];
    }

    toggleLot(lot) {
        this.state.sel[lot.id] = !this.state.sel[lot.id];
    }

    groupSelCount(group) {
        return group.lots.filter((l) => this.state.sel[l.id]).length;
    }

    toggleGroup(group) {
        const all = this.groupSelCount(group) === group.lots.length;
        for (const l of group.lots) {
            this.state.sel[l.id] = !all;
        }
    }

    toggleAll() {
        const all = this.selCount === this.cart.items.length;
        for (const item of this.cart.items) {
            this.state.sel[item.id] = !all;
        }
    }

    _assertSelection() {
        return this.selectedIds.length > 0;
    }
    
    // ── Quitar del carrito ──
    async removeLot(lot) {
        await this._removeIds([lot.id]);
    }

    async removeSelected() {
        if (!this._assertSelection()) {
            return;
        }
        await this._removeIds(this.selectedIds);
    }

    async _removeIds(ids) {
        if (!this.props.onRemoveItems || !ids.length) {
            return;
        }
        await this.props.onRemoveItems(ids);
        for (const id of ids) {
            delete this.state.sel[id];
        }
        if (this.cart.totalLots === 0) {
            this.props.close();
        }
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
        if (!this._assertSelection()) {
            return;
        }
        this.props.close();
        this.props.onCreateHolds(this.selectedIds);
    }
    
    createSaleOrder() {
        // ✅ VALIDACIÓN DE PERMISOS
        if (!this.cart.hasSalesPermissions) {
            this.props.close();
            return;
        }
        if (!this._assertSelection()) {
            return;
        }
        this.props.close();
        this.props.onCreateSaleOrder(this.selectedIds);
    }
    
    createTransfer() {
        // ✅ VALIDACIÓN DE PERMISOS
        if (!this.cart.hasInventoryPermissions) {
            this.props.close();
            return;
        }
        if (!this._assertSelection()) {
            return;
        }
        this.props.close();
        this.props.onCreateTransfer(this.selectedIds);
    }
    
    // ✅ NUEVO MÉTODO: IMPRIMIR ETIQUETAS
    printLabels() {
        if (!this._assertSelection()) {
            return;
        }
        this.props.close();
        this.props.onPrintLabels(this.selectedIds);
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
    onRemoveItems: { type: Function, optional: true },
    onCreateHolds: Function,
    onCreateSaleOrder: Function,
    onCreateTransfer: Function,
    onPrintLabels: Function, // ✅ AGREGADO EN PROPS
};