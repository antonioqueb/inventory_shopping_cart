/** @odoo-module **/
// Compartir el PDF por la hoja NATIVA (Web Share API) DENTRO del gesto del
// usuario — igual que las fotos del inventario visual. El payload (reporte,
// nombre, mensaje) ya viene precalculado en el registro del wizard, así que
// el click solo descarga el PDF y abre la hoja: el contacto se elige ahí.
// Fallback sin Web Share: wa.me/?text= con liga (selector de contacto de
// WhatsApp).
import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class SomWhatsappShare extends Component {
    static template = "inventory_shopping_cart.SomWhatsappShare";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    get data() {
        return this.props.record.data;
    }

    async onShare() {
        const d = this.data;
        if (!d.x_report_name) {
            this.notification.add("El documento aún no está listo, intenta de nuevo.", { type: "warning" });
            return;
        }
        try {
            const resp = await fetch(`/report/pdf/${d.x_report_name}/${d.res_id}`);
            if (resp.ok) {
                const blob = await resp.blob();
                const file = new File([blob], d.x_filename || "documento.pdf", {
                    type: "application/pdf",
                });
                if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
                    await navigator.share({ files: [file], text: d.x_message || "" });
                    this.notification.add("Documento compartido", { type: "success" });
                    this.orm.call("som.whatsapp.send", "log_shared",
                        [d.res_model, d.res_id, d.report_choice]).catch(() => {});
                    return;
                }
            }
        } catch (err) {
            if (err && err.name === "AbortError") {
                return; // el usuario cerró la hoja
            }
        }
        // Fallback: wa.me con selector de contacto y liga de descarga
        try {
            const wa = await this.orm.call("som.whatsapp.send", "get_fallback_wa_url",
                [d.res_model, d.res_id, d.report_choice]);
            window.open(wa, "_blank");
            this.orm.call("som.whatsapp.send", "log_shared",
                [d.res_model, d.res_id, d.report_choice]).catch(() => {});
        } catch (err) {
            this.notification.add("No se pudo preparar el documento.", { type: "danger" });
        }
    }
}

registry.category("view_widgets").add("som_whatsapp_share", {
    component: SomWhatsappShare,
});
