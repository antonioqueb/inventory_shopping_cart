/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class LabelWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        
        this.state = useState({
            selectedFormat: '10x5', // Default
            isGenerating: false,
        });
        
        this.formats = [
            { id: '10x5', name: 'Estándar (10x5 cm)', icon: 'fa-tag', desc: 'Etiqueta básica con código de barras' },
            { id: '17.5x1', name: 'Canto/Lomo (17.5x1 cm)', icon: 'fa-minus', desc: 'Etiqueta delgada para bordes' },
            { id: '20x10', name: 'Grande (20x10 cm)', icon: 'fa-id-card', desc: 'Detalle completo y código grande' },
        ];
    }
    
    selectFormat(formatId) {
        this.state.selectedFormat = formatId;
    }
    
    async downloadZpl() {
        this.state.isGenerating = true;
        try {
            const result = await this.orm.call(
                "stock.quant",
                "generate_zpl_labels",
                [],
                {
                    selected_lots: this.props.selectedLots,
                    label_format: this.state.selectedFormat
                }
            );
            
            if (result.success) {
                // Crear un Blob y descargarlo
                const blob = new Blob([result.zpl_data], { type: 'text/plain' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = result.filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
                
                this.notification.add("Archivo ZPL generado correctamente", { type: "success" });
                this.props.close();
            } else {
                this.notification.add(result.message || "Error al generar etiquetas", { type: "danger" });
            }
        } catch (error) {
            console.error("Error generando ZPL:", error);
            this.notification.add("Error de conexión al generar etiquetas", { type: "danger" });
        } finally {
            this.state.isGenerating = false;
        }
    }
}

LabelWizard.template = "inventory_shopping_cart.LabelWizard";
LabelWizard.components = { Dialog };
LabelWizard.props = {
    close: Function,
    selectedLots: Array,
};