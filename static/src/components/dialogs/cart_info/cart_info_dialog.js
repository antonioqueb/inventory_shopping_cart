/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/**
 * Información del estado EN CARRITO de un lote — mismo lenguaje visual que
 * el diálogo de apartado (reutiliza las clases hold-info-* del inventario
 * visual: cero CSS duplicado).
 */
export class CartInfoDialog extends Component {
    setup() {
        this.cartInfo = this.props.cartInfo || {};
        this.detailData = this.props.detailData || {};
    }

    get hoursLeftLabel() {
        const h = Number(this.cartInfo.hours_left || 0);
        if (h <= 0) {
            return "por liberarse";
        }
        if (h < 1) {
            return `${Math.round(h * 60)} min restantes`;
        }
        return `${h.toFixed(1)} h restantes`;
    }
}

CartInfoDialog.template = "inventory_shopping_cart.CartInfoDialog";
CartInfoDialog.components = { Dialog };
CartInfoDialog.props = {
    cartInfo: { type: Object, optional: true },
    detailData: { type: Object, optional: true },
    close: { type: Function, optional: true },
    title: { type: String, optional: true },
    size: { type: String, optional: true },
};
