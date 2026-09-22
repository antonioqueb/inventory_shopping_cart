/** @odoo-module **/

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Niveles reservados al mayorista/autorizador (3 y 4). El Precio 5 es el
// piso absoluto y se filtra aparte: solo autorizadores de precio y visores
// del Dashboard lo ven.
// P3 ("minimum") abierto a toda la fuerza de ventas (31 ago 2026); P4 sigue siendo de mayoristas.
const MAYORISTA_LEVELS = new Set(["level_4"]);

export class PriceLevelSelectorField extends Component {
    static template = "inventory_shopping_cart.PriceLevelSelectorField";
    static props = {
        ...standardFieldProps,
        inlinePrice: { type: Boolean, optional: true },
    };

    setup() {
        this.selectRef = useRef("select");
        this.priceInputRef = useRef("priceInput");
        // "Personalizado" solo se lee con el dropdown ABIERTO; cerrado
        // la opción se abrevia a "PP" para no comerse la columna.
        // pickLevel: con Personalizado activo, el usuario pidió volver a
        // la lista de niveles (la celda muestra el select en vez del monto).
        // focusPrice: al elegir Personalizado, el input del monto toma el
        // foco en cuanto se pinta.
        this.ui = useState({ open: false, pickLevel: false, focusPrice: false });

        // CAPTURA PENDIENTE (21 sep 2026, RES/00837): el monto tecleado en el
        // input inline solo llegaba al registro con el evento change (blur).
        // Si el usuario pulsaba Guardar directo, el guardado corría antes de
        // que el cambio se aplicara: la vista mostraba el precio nuevo pero
        // la BD conservaba el viejo y al refrescar "se regresaba". Igual que
        // useInputField del core, se confirma lo tecleado cuando el modelo lo
        // pide antes de guardar.
        const { model } = this.props.record;
        useBus(model.bus, "WILL_SAVE_URGENTLY", () => this.commitPrice());
        useBus(model.bus, "NEED_LOCAL_CHANGES", (ev) => ev.detail.proms.push(this.commitPrice()));

        useEffect(
            () => {
                const input = this.priceInputRef.el;
                if (input && this.ui.focusPrice) {
                    this.ui.focusPrice = false;
                    input.focus();
                    input.select();
                }
                const select = this.selectRef.el;
                if (select && this.ui.pickLevel && !this.ui.open) {
                    select.focus();
                    if (typeof select.showPicker === "function") {
                        try {
                            select.showPicker();
                        } catch (_e) {
                            // showPicker exige gesto del usuario; el foco basta.
                        }
                    }
                }
            },
            () => [this.value, this.ui.pickLevel, this.ui.focusPrice]
        );

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
                this.props.record.data.x_can_use_level_5_price,
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
        // Sin el campo en la vista se NIEGA. Antes caía a
        // canUseCustomPrice, que siempre es true: cualquier vista que
        // olvidara declarar x_can_use_minimum_price le abría los niveles
        // 3 y 4 al vendedor con precios limitados.
        return Boolean(this.props.record.data.x_can_use_level_4_price
            ?? this.props.record.data.x_can_use_minimum_price);
    }

    get canUseMinimumPrice() {
        return Boolean(this.props.record.data.x_can_use_minimum_price);
    }

    get canUseLevel5Price() {
        // Sin el campo en la vista, el Precio 5 NO se ofrece: es el piso
        // absoluto y su ausencia es el default seguro.
        return Boolean(this.props.record.data.x_can_use_level_5_price);
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

    async commitPrice() {
        const el = this.priceInputRef.el;
        const fname = this.priceFieldName;
        if (!el || !fname || this.props.readonly) {
            return;
        }
        let val = parseFloat(String(el.value).replace(",", "."));
        if (!isFinite(val) || val < 0) {
            val = 0;
        }
        if (Math.abs(val - this.priceValue) > 1e-9) {
            await this.props.record.update({ [fname]: val });
        }
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

    onPriceKeydown(ev) {
        // Enter confirma el monto sin salir de la fila; Escape regresa a
        // la lista de niveles sin perder lo capturado.
        if (ev.key === "Enter") {
            ev.preventDefault();
            ev.stopPropagation();
            ev.target.blur();
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            ev.stopPropagation();
            this.onReopenLevels();
        }
    }

    onReopenLevels() {
        this.ui.pickLevel = true;
        this.ui.open = true;
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
                if (val === "minimum" && !this.canUseMinimumPrice) {
                    return false;
                }
                if (MAYORISTA_LEVELS.has(val) && !this.canUseMayoristaPrices) {
                    return false;
                }

                if (val === "level_5" && !this.canUseLevel5Price) {
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
        this.ui.pickLevel = false;
        const newValue = ev.target.value;
        if (newValue === "custom" && this.showInlinePrice) {
            // El input del monto sustituye al select y queda listo para
            // teclear: un solo clic en Personalizado y a escribir.
            this.ui.focusPrice = true;
        }
        this.props.record.update({ [this.props.name]: newValue });
    }

    onSelectOpen() {
        this.ui.open = true;
    }

    onSelectClose() {
        this.ui.open = false;
        // Cerró la lista sin cambiar de nivel: la celda vuelve al monto.
        this.ui.pickLevel = false;
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
