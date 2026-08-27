/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { CartDialog } from "../dialogs/cart_dialog/cart_dialog";
import { HoldWizard } from "../dialogs/hold_wizard/hold_wizard";
import { SaleOrderWizard } from "../dialogs/sale_order_wizard/sale_order_wizard";
import { TransferWizard } from "../dialogs/transfer_wizard/transfer_wizard";
import { LabelWizard } from "../dialogs/label_wizard/label_wizard";

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
            onRemoveItems: (ids) => this.removeItemsFromCart(ids),
            onCreateHolds: (ids) => this.openHoldWizard(ids),
            onCreateSaleOrder: (ids) => this.openSaleOrderWizard(ids),
            onCreateTransfer: (ids) => this.openTransferWizard(ids),
            onPrintLabels: (ids) => this.openLabelWizard(ids)
        });
    },

    // ── Selección parcial del carrito ──
    // La acción aplica SOLO a los lotes palomeados en el diálogo; el
    // resto se queda VIVO en el carrito para otra acción.
    _cartSubset(selectedIds) {
        const ids = selectedIds && selectedIds.length
            ? new Set(selectedIds) : null;
        const items = ids
            ? this.cart.items.filter((i) => ids.has(i.id))
            : [...this.cart.items];
        const groups = {};
        for (const [pid, g] of Object.entries(this.cart.productGroups)) {
            const lots = (g.lots || []).filter((l) => !ids || ids.has(l.id));
            if (!lots.length) {
                continue;
            }
            groups[pid] = {
                ...g,
                lots,
                total_quantity: lots.reduce((a, l) => a + (l.quantity || 0), 0),
            };
        }
        return { items, groups, partial: !!ids && items.length < this.cart.items.length };
    },

    async consumeCartItems(selectedIds) {
        const sub = this._cartSubset(selectedIds);
        if (!sub.partial) {
            await this.clearCart();
            return;
        }
        const ids = new Set(sub.items.map((i) => i.id));
        for (const id of ids) {
            try {
                await this.orm.call("shopping.cart", "remove_from_cart", [id]);
            } catch (e) {
                console.warn("[CART] No se pudo retirar el item", id, e);
            }
        }
        this.cart.items = this.cart.items.filter((i) => !ids.has(i.id));
        // updateCartSummary también reconstruye productGroups
        this.updateCartSummary();
    },
    
    async openHoldWizard(selectedIds) {
        if (!this.cart.hasSalesPermissions) {
            this.notification.add(
                "No tiene permisos para crear apartados. Contacte al administrador.",
                { type: "warning" }
            );
            return;
        }

        await this.syncCartToDB();
        const sub = this._cartSubset(selectedIds);

        this.dialog.add(HoldWizard, {
            selectedLots: sub.items.map(item => item.id),
            productGroups: sub.groups,
            onSuccess: async () => {
                // Solo lo palomeado sale del carrito; el resto sigue vivo.
                await this.consumeCartItems(selectedIds);
            }
        });
    },
    
    async openSaleOrderWizard(selectedIds) {
        if (!this.cart.hasSalesPermissions) {
            this.notification.add(
                "No tiene permisos para crear órdenes de venta. Contacte al administrador.", 
                { type: "warning" }
            );
            return;
        }
        
        const sub = this._cartSubset(selectedIds);
        const lotsWithHold = sub.items.filter(item => item.tiene_hold);

        if (lotsWithHold.length > 0) {
            this.notification.add("Hay lotes apartados en tu selección. Desmárcalos o usa 'Eliminar Apartados'.", { type: "warning", sticky: true });
            return;
        }

        await this.syncCartToDB();

        this.dialog.add(SaleOrderWizard, {
            productGroups: sub.groups,
            onSuccess: async () => {
                await this.consumeCartItems(selectedIds);
            }
        });
    },
    
    async openTransferWizard(selectedIds) {
        if (!this.cart.hasInventoryPermissions) {
            this.notification.add(
                "No tiene permisos para crear traslados. Contacte al administrador.", 
                { type: "warning" }
            );
            return;
        }
        
        await this.syncCartToDB();
        const sub = this._cartSubset(selectedIds);

        this.dialog.add(TransferWizard, {
            selectedLots: sub.items.map(item => item.id),
            productGroups: sub.groups,
            onSuccess: async () => {
                await this.consumeCartItems(selectedIds);
            }
        });
    },

    async openLabelWizard(selectedIds) {
        if (this.cart.totalLots === 0) {
            this.notification.add("No hay items en el carrito para imprimir", { type: "warning" });
            return;
        }
        
        await this.syncCartToDB();
        const sub = this._cartSubset(selectedIds);

        this.dialog.add(LabelWizard, {
            selectedLots: sub.items.map(item => item.id)
        });
    }
});

// Importación segura para evitar errores si ProductRow no está exportado correctamente en el módulo base
try {
    const { ProductRow } = require("@inventory_visual_enhanced/components/product_row/product_row");
    if (ProductRow) {
        patch(ProductRow.prototype, {});
    }
} catch (e) {
    console.warn("No se pudo parchear ProductRow, posiblemente no sea necesario o la ruta cambió.", e);
}