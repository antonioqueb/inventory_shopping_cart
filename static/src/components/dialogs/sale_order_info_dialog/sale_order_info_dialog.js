/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class SaleOrderInfoDialog extends Component {
    setup() {
        this.action = useService("action");
        this.info = this.props.info || {};
    }

    openSaleOrder() {
        const orderId = this.info.sale_order_id;

        if (!orderId) {
            return;
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: orderId,
            views: [[false, "form"]],
            target: "current",
        });

        this.props.close();
    }

    formatNumber(value) {
        const num = Number(value || 0);

        return new Intl.NumberFormat("es-MX", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(num);
    }

    formatCurrency(value) {
        const symbol = this.info.currency_symbol || "$";
        return `${symbol}${this.formatNumber(value || 0)}`;
    }

    get hasOrder() {
        return Boolean(this.info.sale_order_id);
    }

    get paymentBadgeClass() {
        return `so-payment-badge so-payment-badge--${this.info.payment_state || "none"}`;
    }
}

SaleOrderInfoDialog.template = "inventory_shopping_cart.SaleOrderInfoDialog";
SaleOrderInfoDialog.components = { Dialog };
SaleOrderInfoDialog.props = {
    close: Function,
    info: Object,
};