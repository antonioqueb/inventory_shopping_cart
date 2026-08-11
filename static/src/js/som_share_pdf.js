/** @odoo-module **/
// Compartir PDF por la hoja NATIVA del sistema (Web Share API): en móvil
// abre el selector (WhatsApp incluido) con el ARCHIVO adjunto de verdad —
// mismo patrón que el visor de fotos del inventario visual. Fallback en
// navegadores sin Web Share (escritorio): wa.me con mensaje + liga.
import { registry } from "@web/core/registry";

registry.category("actions").add("som_share_pdf", async (env, action) => {
    const p = (action && action.params) || {};
    try {
        const resp = await fetch(p.url);
        if (resp.ok) {
            const blob = await resp.blob();
            const file = new File([blob], p.filename || "documento.pdf", {
                type: "application/pdf",
            });
            if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
                try {
                    await navigator.share({ text: p.message || "", files: [file] });
                    env.services.notification.add("Documento compartido", { type: "success" });
                    return;
                } catch (err) {
                    if (err && err.name === "AbortError") {
                        return; // el usuario cerró la hoja: no hacer nada
                    }
                }
            }
        }
    } catch (err) {
        // cae al fallback
    }
    if (p.wa_url) {
        window.open(p.wa_url, "_blank");
    }
});
