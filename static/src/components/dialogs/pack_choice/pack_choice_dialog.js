/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/**
 * Venta por empaque: la cantidad elegida no cuadra en empaques completos y
 * el VENDEDOR decide a cuántos ajustar (opciones cercanas o un número libre
 * hasta lo disponible). Nada se agrega al carrito hasta que elige.
 */
export class PackChoiceDialog extends Component {
    setup() {
        const info = this.props.info || {};
        this.info = info;
        this.state = useState({ custom: (info.options && info.options[0]) ? info.options[0].packs : 1 });
    }

    // Las plantillas OWL no exponen globales (Number, Math…): todo
    // formato se hace aquí. Llamar Number() en el XML tumbaba el diálogo
    // ("ctx.Number is not a function", 4 sep 2026).
    fmt(value) {
        return Number(value || 0).toFixed(2);
    }

    qtyFor(packs) {
        return (Number(packs) * Number(this.info.qty_per_pack || 0)).toFixed(2);
    }

    get customValid() {
        const n = parseInt(this.state.custom, 10);
        return Number.isInteger(n) && n >= 1 && n <= (this.info.max_packs || 0);
    }

    choose(packs) {
        const n = parseInt(packs, 10);
        if (!Number.isInteger(n) || n < 1 || n > (this.info.max_packs || 0)) return;
        this.props.onChoose(n);
        this.props.close();
    }

    cancel() {
        if (this.props.onCancel) this.props.onCancel();
        this.props.close();
    }
}

PackChoiceDialog.template = "inventory_shopping_cart.PackChoiceDialog";
PackChoiceDialog.components = { Dialog };
PackChoiceDialog.props = {
    info: { type: Object },
    onChoose: { type: Function },
    onCancel: { type: Function, optional: true },
    close: { type: Function, optional: true },
};
