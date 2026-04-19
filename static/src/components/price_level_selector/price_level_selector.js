/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class PriceLevelSelectorField extends Component {
    static template = "inventory_shopping_cart.PriceLevelSelectorField";
    static props = { ...standardFieldProps };

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

    formatPrice(value) {
        const num = Number(value) || 0;
        const formatted = num.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        return `${formatted} ${this.currency}`;
    }

    get options() {
        const price1 = this.props.record.data.x_price_1_value || 0;
        const price2 = this.props.record.data.x_price_2_value || 0;
        return this.rawSelection.map(([val, label]) => {
            if (val === "high") {
                return [val, `${label} — ${this.formatPrice(price1)}`];
            }
            if (val === "medium") {
                return [val, `${label} — ${this.formatPrice(price2)}`];
            }
            return [val, label];
        });
    }

    get displayLabel() {
        const opt = this.options.find(([v]) => v === this.value);
        return opt ? opt[1] : "";
    }

    onChange(ev) {
        this.props.record.update({ [this.props.name]: ev.target.value });
    }
}

export const priceLevelSelectorField = {
    component: PriceLevelSelectorField,
    displayName: "Nivel de Precio con Monto",
    supportedTypes: ["selection"],
    fieldDependencies: [
        { name: "x_price_1_value", type: "float" },
        { name: "x_price_2_value", type: "float" },
        { name: "x_price_level_currency", type: "char" },
    ],
};

registry.category("fields").add("price_level_selector", priceLevelSelectorField);
