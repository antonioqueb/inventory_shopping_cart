/** @odoo-module **/

import { Component, useEffect, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const MAYORISTA_LEVELS = new Set(["minimum", "level_4", "level_5"]);

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
                this.props.record.data.x_price_4_value,
                this.props.record.data.x_price_5_value,
                this.props.record.data.x_price_level_currency,
                this.props.record.data.x_can_use_custom_price,
                this.props.record.data.x_can_use_minimum_price,
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

    get canUseCustomPrice() {
        return Boolean(this.props.record.data.x_can_use_custom_price);
    }

    get canUseMayoristaPrices() {
        const explicitFlag = this.props.record.data.x_can_use_minimum_price;

        if (explicitFlag === undefined) {
            return this.canUseCustomPrice;
        }

        return Boolean(explicitFlag);
    }

    formatPrice(value) {
        const num = Number(value) || 0;
        const formatted = num.toLocaleString("es-MX", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        });
        return `$${formatted} ${this.currency}`;
    }

    get options() {
        const price1 = this.props.record.data.x_price_1_value || 0;
        const price2 = this.props.record.data.x_price_2_value || 0;
        const price3 = this.props.record.data.x_price_3_value || 0;
        const price4 = this.props.record.data.x_price_4_value || 0;
        const price5 = this.props.record.data.x_price_5_value || 0;

        return this.rawSelection
            .filter(([val]) => {
                if (MAYORISTA_LEVELS.has(val) && !this.canUseMayoristaPrices) {
                    return false;
                }

                if (val === "custom" && !this.canUseCustomPrice) {
                    return false;
                }

                return true;
            })
            .map(([val, label]) => {
                if (val === "high") {
                    return [val, `${label} ${this.formatPrice(price1)}`];
                }

                if (val === "medium") {
                    return [val, `${label} ${this.formatPrice(price2)}`];
                }

                if (val === "minimum") {
                    return [val, `${label} ${this.formatPrice(price3)}`];
                }

                if (val === "level_4") {
                    return [val, `${label} ${this.formatPrice(price4)}`];
                }

                if (val === "level_5") {
                    return [val, `${label} ${this.formatPrice(price5)}`];
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
};

registry.category("fields").add("price_level_selector", priceLevelSelectorField);
