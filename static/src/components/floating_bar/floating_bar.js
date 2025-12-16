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
            onCreateHolds: () => this.openHoldWizard(),
            onCreateSaleOrder: () => this.openSaleOrderWizard(),
            onCreateTransfer: () => this.openTransferWizard(),
            onPrintLabels: () => this.openLabelWizard()
        });
    },
    
    async openHoldWizard() {
        if (!this.cart.hasSalesPermissions) {
            this.notification.add(
                "No tiene permisos para crear apartados. Contacte al administrador.", 
                { type: "warning" }
            );
            return;
        }
        
        await this.syncCartToDB();
        
        this.dialog.add(HoldWizard, {
            selectedLots: this.cart.items.map(item => item.id),
            productGroups: this.cart.productGroups,
            onSuccess: async () => {
                // CORRECCIÓN: Usar reload para asegurar que los 'holds' se visualicen
                // this.clearCart(); // Esto solo limpia la memoria JS
                // await this.searchProducts(); // ESTO CAUSABA EL ERROR
                
                await this.clearCart(); // Limpia visualmente el carrito
                window.location.reload(); // Recarga la página para ver los candados nuevos
            }
        });
    },
    
    async openSaleOrderWizard() {
        if (!this.cart.hasSalesPermissions) {
            this.notification.add(
                "No tiene permisos para crear órdenes de venta. Contacte al administrador.", 
                { type: "warning" }
            );
            return;
        }
        
        const lotsWithHold = this.cart.items.filter(item => item.tiene_hold);
        
        if (lotsWithHold.length > 0) {
            this.notification.add("Hay lotes apartados en el carrito. Use 'Eliminar Apartados' primero.", { type: "warning", sticky: true });
            return;
        }
        
        await this.syncCartToDB();
        
        this.dialog.add(SaleOrderWizard, {
            productGroups: this.cart.productGroups,
            onSuccess: async () => {
                await this.clearCart();
                // En venta no es estrictamente necesario recargar si se redirige a la orden,
                // pero si te quedas en el inventario, es mejor recargar.
                window.location.reload();
            }
        });
    },
    
    async openTransferWizard() {
        if (!this.cart.hasInventoryPermissions) {
            this.notification.add(
                "No tiene permisos para crear traslados. Contacte al administrador.", 
                { type: "warning" }
            );
            return;
        }
        
        await this.syncCartToDB();
        
        this.dialog.add(TransferWizard, {
            selectedLots: this.cart.items.map(item => item.id),
            productGroups: this.cart.productGroups,
            onSuccess: async () => {
                // CORRECCIÓN: Igual que en HoldWizard
                await this.clearCart();
                window.location.reload();
            }
        });
    },

    async openLabelWizard() {
        if (this.cart.totalLots === 0) {
            this.notification.add("No hay items en el carrito para imprimir", { type: "warning" });
            return;
        }
        
        await this.syncCartToDB();
        
        this.dialog.add(LabelWizard, {
            selectedLots: this.cart.items.map(item => item.id)
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