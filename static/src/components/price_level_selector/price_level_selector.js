/** @odoo-module **/

import { Component, useEffect, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class PriceLevelSelectorField extends Component {
    static template = "inventory_shopping_cart.PriceLevelSelectorField";
    static props = { ...standardFieldProps };

    setup() {
        this.selectRef = useRef("select");

        useEffect(
            () => {
                if (this.selectRef.el) {
                    this.selectRef.el.value = this.value;
                }
            },
            () => [
                this.value,
                this.props.record.data.x_price_1_value,
                this.props.record.data.x_price_2_value,
                this.props.record.data.x_price_3_value,
                this.props.record.data.x_price_level_currency,
                this.props.record.data.x_can_use_custom_price,
            ]
        );
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get rawSelection() {
        const field = this.props.record.fields[this.props.name];
        return (field && field.selection) || [];
    }

    get currency() {
        return this.props.record.data.x_price_level_currency || "USD";
    }

    get canUseRestrictedPrices() {
        /*
         * En sale.order.line este campo puede no existir.
         * En stock.lot.hold.order.line sí existe y representa autorizador.
         *
         * Regla:
         * - false / inexistente: solo Precio 1 y Precio 2.
         * - true: Precio 1, Precio 2, Precio 3 y Personalizado.
         */
        return Boolean(this.props.record.data.x_can_use_custom_price);
    }

    formatPrice(value) {
        const num = Number(value) || 0;
        const formatted = num.toLocaleString("es-MX", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        return `$${formatted} ${this.currency}`;
    }

    get options() {
        const price1 = this.props.record.data.x_price_1_value || 0;
        const price2 = this.props.record.data.x_price_2_value || 0;
        const price3 = this.props.record.data.x_price_3_value || 0;

        return this.rawSelection
            .filter(([val]) => {
                if ((val === "minimum" || val === "custom") && !this.canUseRestrictedPrices) {
                    return false;
                }
                return true;
            })
            .map(([val, label]) => {
                if (val === "high") {
                    return [val, `${label} — ${this.formatPrice(price1)}`];
                }

                if (val === "medium") {
                    return [val, `${label} — ${this.formatPrice(price2)}`];
                }

                if (val === "minimum") {
                    return [val, `${label} — ${this.formatPrice(price3)}`];
                }

                return [val, label];
            });
    }

    get displayLabel() {
        const opt = this.options.find(([v]) => v === this.value);
        return opt ? opt[1] : "";
    }

    onChange(ev) {
        const value = ev.target.value;
        this.props.record.update({ [this.props.name]: value });
    }
}

export const priceLevelSelectorField = {
    component: PriceLevelSelectorField,
    displayName: "Nivel de Precio con Monto",
    supportedTypes: ["selection"],

    /*
     * No declarar fieldDependencies aquí.
     * Este widget se usa en varios modelos.
     * Los campos auxiliares se cargan desde la vista como invisibles.
     */
};

registry.category("fields").add("price_level_selector", priceLevelSelectorField);