/** @odoo-module */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * Botón "+" grande arriba de las líneas de la orden.
 *
 * Los controles nativos (Agregar un producto / sección / nota / Catálogo)
 * quedan al fondo de la lista y son difíciles de ver. Este botón delega el
 * clic en el control nativo "Agregar un producto", por lo que el
 * comportamiento (nueva fila editable al fondo) es exactamente el estándar.
 */
export class SaleQuickAddButton extends Component {
    static template = "inventory_shopping_cart.SaleQuickAddButton";
    static props = { ...standardWidgetProps };

    onClick(ev) {
        const form = ev.target.closest(".o_form_view");
        if (!form) {
            return;
        }
        // Primer ancla del control de creación dentro de la lista principal
        // de líneas (la pestaña Logística no tiene controles: create="0").
        const addLink = form.querySelector(
            "div[name='order_line'] .o_field_x2many_list_row_add a"
        );
        if (addLink) {
            addLink.scrollIntoView({ block: "center", behavior: "smooth" });
            addLink.click();
        }
    }
}

registry.category("view_widgets").add("sale_quick_add_button", {
    component: SaleQuickAddButton,
});
