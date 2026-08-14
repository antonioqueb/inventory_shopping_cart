/** @odoo-module **/

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// El Precio 3 ('minimum') es LIBRE para todo vendedor; solo los
// niveles 4 y 5 quedan reservados a mayoristas/autorizadores.
const MAYORISTA_LEVELS = new Set(["level_4", "level_5"]);

export class PriceLevelSelectorField extends Component {
    static template = "inventory_shopping_cart.PriceLevelSelectorField";
    static props = {
        ...standardFieldProps,
        inlinePrice: { type: Boolean, optional: true },
    };

    setup() {
        this.selectRef = useRef("select");
        // "Personalizado" solo se lee con el dropdown ABIERTO; cerrado
        // la opción se abrevia a "PP" para no comerse la columna.
        this.ui = useState({ open: false });

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

    // ── Precio personalizado inline (opción {'inline_price': true}) ──────────
    // La celda del selector absorbe también la captura del precio: al elegir
    // "Personalizado" aparece el input en la MISMA columna (la columna de
    // precio unitario se oculta en la vista). El nombre del campo de precio
    // se autodetecta para servir a OV (price_unit) y apartados
    // (precio_unitario).
    get priceFieldName() {
        const fields = this.props.record.fields || {};
        if ("price_unit" in fields) {
            return "price_unit";
        }
        if ("precio_unitario" in fields) {
            return "precio_unitario";
        }
        return null;
    }

    get showInlinePrice() {
        return Boolean(this.props.inlinePrice) && Boolean(this.priceFieldName);
    }

    get priceValue() {
        const fname = this.priceFieldName;
        return fname ? Number(this.props.record.data[fname]) || 0 : 0;
    }

    async onPriceChange(ev) {
        const fname = this.priceFieldName;
        if (!fname) {
            return;
        }
        let val = parseFloat(String(ev.target.value).replace(",", "."));
        if (!isFinite(val) || val < 0) {
            val = 0;
        }
        await this.props.record.update({ [fname]: val });
    }

    formatPrice(value, decimals = 0) {
        // Sin sufijo de divisa: la lista de precios de la orden ya la define.
        const num = Number(value) || 0;
        const formatted = num.toLocaleString("es-MX", {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
        return `$${formatted}`;
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
                if (val === "custom") {
                    return [val, this.ui.open ? label : "PP"];
                }

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
        if (this.value === "custom" && this.showInlinePrice) {
            return `PP ${this.formatPrice(this.priceValue, 2)}`;
        }
        const opt = this.options.find(([v]) => v === this.value);
        return opt ? opt[1] : "";
    }

    onChange(ev) {
        this.ui.open = false;
        this.props.record.update({ [this.props.name]: ev.target.value });
    }

    onSelectOpen() {
        this.ui.open = true;
    }

    onSelectClose() {
        this.ui.open = false;
    }
}

export const priceLevelSelectorField = {
    component: PriceLevelSelectorField,
    displayName: "Nivel de Precio con Monto",
    supportedTypes: ["selection"],
    extractProps: ({ options }) => ({
        inlinePrice: Boolean(options && options.inline_price),
    }),
};

registry.category("fields").add("price_level_selector", priceLevelSelectorField);
