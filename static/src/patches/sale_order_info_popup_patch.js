/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { SaleOrderInfoDialog } from "../components/dialogs/sale_order_info_dialog/sale_order_info_dialog";

const InventoryVisualController = registry.category("actions").get("inventory_visual_enhanced");

patch(InventoryVisualController.prototype, {
    async openSaleOrderInfoPopup(detail) {
        if (!detail || !detail.id) {
            this.notification.add("No se pudo identificar el lote seleccionado.", {
                type: "warning",
            });
            return;
        }

        try {
            const result = await this.orm.call(
                "stock.quant",
                "get_sale_order_popup_info",
                [],
                {
                    quant_id: detail.id,
                }
            );

            if (!result || !result.success) {
                this.notification.add(
                    result && result.message
                        ? result.message
                        : "No se encontró información de orden de venta para este lote.",
                    { type: "warning" }
                );
                return;
            }

            this.dialog.add(SaleOrderInfoDialog, {
                info: result,
            });
        } catch (error) {
            console.error("[SO POPUP] Error cargando información:", error);
            this.notification.add(
                error.message || "Error al cargar la información de la orden.",
                { type: "danger" }
            );
        }
    },
});