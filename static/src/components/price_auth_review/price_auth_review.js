/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * Interfaz de revisión de Autorizaciones de Precio.
 *
 * - Autorizador: ve por producto los 3 niveles (P1/P2/P3), el costo, el
 *   precio prometido vs autorizado (editable) y el TOTAL — sin lotes.
 * - Vendedor: ve su solicitud (producto, cantidad, precio prometido) y el
 *   total, sin niveles ni costos.
 */
export class PriceAuthReview extends Component {
    static template = "inventory_shopping_cart.PriceAuthReview";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ data: null, busy: false });
        onWillStart(() => this.load());
    }

    get resId() {
        return this.props.record.resId;
    }

    get d() {
        return this.state.data || {};
    }

    async load() {
        if (!this.resId) {
            return;
        }
        this.state.data = await this.orm.call(
            "price.authorization", "get_review_data", [this.resId]
        );
    }

    async reloadAll() {
        await this.load();
        try {
            await this.props.record.load();
        } catch {
            // El registro se refresca al navegar; el widget ya está al día.
        }
    }

    money(v) {
        const n = parseFloat(v || 0);
        return "$" + n.toLocaleString("es-MX", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    num(v) {
        return parseFloat(v || 0).toLocaleString("es-MX", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    // Semáforo del precio prometido contra la escalera.
    levelTone(line) {
        if (line.price_level === "below_minimum") {
            return "danger";
        }
        if (line.price_level === "minimum") {
            return "warn";
        }
        return "ok";
    }

    levelLabel(line) {
        if (line.price_level === "below_minimum") {
            return "Debajo del Precio 3";
        }
        if (line.price_level === "minimum") {
            return "Entre Precio 3 y Precio 2";
        }
        return "Dentro de niveles";
    }

    async onPriceChange(line, ev) {
        const val = parseFloat(ev.target.value);
        if (!Number.isFinite(val) || val < 0) {
            ev.target.value = line.authorized_price || 0;
            return;
        }
        await this.orm.call(
            "price.authorization", "set_line_authorized_price",
            [this.resId, line.id, val]
        );
        await this.load();
    }

    async doAction(method) {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            // Guardar cambios pendientes del formulario (p. ej. notas);
            // guardar sin cambios es un no-op.
            await this.props.record.save();
            await this.orm.call("price.authorization", method, [this.resId]);
            this.notification.add(
                method === "action_approve"
                    ? "Solicitud aprobada — la operación se procesó."
                    : "Solicitud rechazada.",
                { type: method === "action_approve" ? "success" : "warning" }
            );
            await this.reloadAll();
        } finally {
            this.state.busy = false;
        }
    }

    approve() {
        return this.doAction("action_approve");
    }

    reject() {
        return this.doAction("action_reject");
    }
}

export const priceAuthReview = {
    component: PriceAuthReview,
};

registry.category("view_widgets").add("price_auth_review", priceAuthReview);
