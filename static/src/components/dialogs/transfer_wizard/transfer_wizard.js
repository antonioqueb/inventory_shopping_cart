/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class TransferWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        
        this.state = useState({
            // Ubicación destino
            searchLocationTerm: '',
            locations: [],
            selectedLocationId: null,
            selectedLocationName: '',
            
            // Notas
            notes: '',
            
            // Usuario
            userName: '',
            userId: null,
            
            // UI
            isCreating: false,
            currentStep: 1,
        });
        
        this.searchTimeout = null;
        this.loadCurrentUser();
    }
    
    async loadCurrentUser() {
        try {
            const result = await this.orm.call(
                'stock.quant',
                'get_current_user_info',
                []
            );
            this.state.userName = result.name;
            this.state.userId = result.id;
        } catch (error) {
            console.error("Error obteniendo usuario actual:", error);
            this.state.userName = 'Usuario Actual';
        }
    }
    
    // ========== UBICACIÓN DESTINO ==========
    
    onSearchLocation(ev) {
        const value = ev.target.value;
        this.state.searchLocationTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchLocations();
        }, 300);
    }
    
    async searchLocations() {
        try {
            const locations = await this.orm.call(
                "stock.quant",
                "get_internal_locations",
                [],
                { search_term: this.state.searchLocationTerm.trim() }
            );
            
            this.state.locations = locations;
        } catch (error) {
            console.error("Error buscando ubicaciones:", error);
            this.notification.add("Error al buscar ubicaciones", { type: "danger" });
        }
    }
    
    selectLocation(location) {
        this.state.selectedLocationId = location.id;
        this.state.selectedLocationName = location.complete_name;
    }
    
    // ========== NAVEGACIÓN ==========
    
    nextStep() {
        if (this.state.currentStep === 1 && !this.state.selectedLocationId) {
            this.notification.add("Debe seleccionar una ubicación destino", { type: "warning" });
            return;
        }
        
        if (this.state.currentStep < 2) {
            this.state.currentStep++;
        }
    }
    
    prevStep() {
        if (this.state.currentStep > 1) {
            this.state.currentStep--;
        }
    }
    
    // ========== CREAR TRASLADO ==========
    
    async createTransfer() {
        if (!this.state.selectedLocationId) {
            this.notification.add("Debe seleccionar una ubicación destino", { type: "warning" });
            return;
        }
        
        this.state.isCreating = true;
        
        try {
            const result = await this.orm.call(
                "stock.picking",
                "create_transfer_from_shopping_cart",
                [],
                {
                    selected_lots: this.props.selectedLots,
                    location_dest_id: this.state.selectedLocationId,
                    notes: this.state.notes
                }
            );
            
            if (result.success) {
                let message = `${result.total_pickings} traslado(s) creado(s) exitosamente:\n\n`;
                result.pickings.forEach(p => {
                    message += `• ${p.name} (${p.location_origin} → ${this.state.selectedLocationName})\n`;
                });
                
                this.notification.add(message, { type: "success", sticky: true });
                this.props.onSuccess();
                this.props.close();
                
                // Abrir el primer traslado
                if (result.pickings.length > 0) {
                    this.action.doAction({
                        type: 'ir.actions.act_window',
                        res_model: 'stock.picking',
                        res_id: result.pickings[0].id,
                        views: [[false, 'form']],
                        target: 'current',
                    });
                }
            }
        } catch (error) {
            console.error("Error creando traslado:", error);
            this.notification.add(error.message || "Error al crear traslado", { type: "danger" });
        } finally {
            this.state.isCreating = false;
        }
    }
    
    formatNumber(num) {
        return new Intl.NumberFormat('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num);
    }
}

TransferWizard.template = "inventory_shopping_cart.TransferWizard";
TransferWizard.components = { Dialog };
TransferWizard.props = {
    close: Function,
    selectedLots: Array,
    productGroups: Object,
    onSuccess: Function,
};