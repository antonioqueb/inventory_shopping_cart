/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class HoldWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        
        this.productIds = Object.keys(this.props.productGroups).map(id => parseInt(id));
        this.currentProductIndex = 0;
        
        this.state = useState({
            // Cliente
            searchPartnerTerm: '',
            partners: [],
            selectedPartnerId: null,
            selectedPartnerName: '',
            showCreatePartner: false,
            newPartnerName: '',
            newPartnerVat: '',
            newPartnerRef: '',
            
            // Proyecto
            searchProjectTerm: '',
            projects: [],
            selectedProjectId: null,
            selectedProjectName: '',
            showCreateProject: false,
            newProjectName: '',
            
            // Arquitecto
            searchArchitectTerm: '',
            architects: [],
            selectedArchitectId: null,
            selectedArchitectName: '',
            showCreateArchitect: false,
            newArchitectName: '',
            newArchitectVat: '',
            newArchitectRef: '',
            
            // Precios
            selectedCurrency: 'USD',
            pricelists: [],
            selectedPricelistId: null,
            productPrices: {},
            productPriceOptions: {},
            
            // Notas
            notas: '',
            
            // Vendedor
            sellerName: '',
            sellerId: null,
            
            // UI
            isCreating: false,
            currentStep: 1,
        });
        
        this.searchTimeout = null;
        this.loadCurrentUser();
        this.loadPricelists();
    }
    
    async loadCurrentUser() {
        try {
            const result = await this.orm.call(
                'stock.quant',
                'get_current_user_info',
                []
            );
            this.state.sellerName = result.name;
            this.state.sellerId = result.id;
        } catch (error) {
            console.error("Error obteniendo usuario actual:", error);
            this.state.sellerName = 'Usuario Actual';
        }
    }
    
    async loadPricelists() {
        try {
            const pricelists = await this.orm.searchRead(
                "product.pricelist",
                [['name', 'in', ['USD', 'MXN']]],
                ['id', 'name', 'currency_id']
            );
            this.state.pricelists = pricelists;
            
            const usd = pricelists.find(p => p.name === 'USD');
            if (usd) {
                this.state.selectedPricelistId = usd.id;
                this.state.selectedCurrency = 'USD';
            }
            
            await this.loadAllProductPrices();
        } catch (error) {
            console.error("Error cargando listas de precios:", error);
            this.notification.add("Error al cargar listas de precios", { type: "warning" });
        }
    }
    
    async loadAllProductPrices() {
        for (const productId of this.productIds) {
            try {
                const prices = await this.orm.call(
                    "product.template",
                    "get_custom_prices",
                    [],
                    {
                        product_id: productId,
                        currency_code: this.state.selectedCurrency
                    }
                );
                
                this.state.productPriceOptions[productId] = prices;
                
                if (prices.length > 0 && !this.state.productPrices[productId]) {
                    this.state.productPrices[productId] = prices[0].value;
                }
            } catch (error) {
                console.error(`Error cargando precios para producto ${productId}:`, error);
            }
        }
    }
    
    async onCurrencyChange(ev) {
        const pricelistName = ev.target.value;
        this.state.selectedCurrency = pricelistName;
        
        const pricelist = this.state.pricelists.find(p => p.name === pricelistName);
        if (pricelist) {
            this.state.selectedPricelistId = pricelist.id;
        }
        
        await this.loadAllProductPrices();
    }
    
    onPriceChange(productId, value) {
        const numValue = parseFloat(value);
        this.state.productPrices[productId] = numValue;
    }
    
    // ========== CLIENTE ==========
    
    onSearchPartner(ev) {
        const value = ev.target.value;
        this.state.searchPartnerTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchPartners();
        }, 300);
    }
    
    async searchPartners() {
        try {
            const partners = await this.orm.call(
                "stock.quant",
                "search_partners",
                [],
                { name: this.state.searchPartnerTerm.trim() }
            );
            
            this.state.partners = partners;
        } catch (error) {
            console.error("Error buscando clientes:", error);
            this.notification.add("Error al buscar clientes", { type: "danger" });
        }
    }
    
    selectPartner(partner) {
        this.state.selectedPartnerId = partner.id;
        this.state.selectedPartnerName = partner.display_name;
        this.state.showCreatePartner = false;
    }
    
    toggleCreatePartner() {
        this.state.showCreatePartner = !this.state.showCreatePartner;
        if (this.state.showCreatePartner) {
            this.state.selectedPartnerId = null;
            this.state.selectedPartnerName = '';
        }
    }
    
    async createPartner() {
        if (!this.state.newPartnerName.trim()) {
            this.notification.add("El nombre del cliente es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_partner",
                [],
                {
                    name: this.state.newPartnerName.trim(),
                    vat: this.state.newPartnerVat.trim(),
                    ref: this.state.newPartnerRef.trim()
                }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectPartner(result.partner);
                this.notification.add(`Cliente "${result.partner.name}" creado exitosamente`, { type: "success" });
                this.state.newPartnerName = '';
                this.state.newPartnerVat = '';
                this.state.newPartnerRef = '';
            }
        } catch (error) {
            console.error("Error creando cliente:", error);
            this.notification.add("Error al crear cliente", { type: "danger" });
        }
    }
    
    // ========== PROYECTO ==========
    
    onSearchProject(ev) {
        const value = ev.target.value;
        this.state.searchProjectTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchProjects();
        }, 300);
    }
    
    async searchProjects() {
        try {
            const projects = await this.orm.call(
                "stock.quant",
                "get_projects",
                [],
                { search_term: this.state.searchProjectTerm.trim() }
            );
            
            this.state.projects = projects;
        } catch (error) {
            console.error("Error buscando proyectos:", error);
            this.notification.add("Error al buscar proyectos", { type: "danger" });
        }
    }
    
    selectProject(project) {
        this.state.selectedProjectId = project.id;
        this.state.selectedProjectName = project.name;
        this.state.showCreateProject = false;
    }
    
    toggleCreateProject() {
        this.state.showCreateProject = !this.state.showCreateProject;
        if (this.state.showCreateProject) {
            this.state.selectedProjectId = null;
            this.state.selectedProjectName = '';
        }
    }
    
    async createProject() {
        if (!this.state.newProjectName.trim()) {
            this.notification.add("El nombre del proyecto es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_project",
                [],
                { name: this.state.newProjectName.trim() }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectProject(result.project);
                this.notification.add(`Proyecto "${result.project.name}" creado exitosamente`, { type: "success" });
                this.state.newProjectName = '';
            }
        } catch (error) {
            console.error("Error creando proyecto:", error);
            this.notification.add("Error al crear proyecto", { type: "danger" });
        }
    }
    
    // ========== ARQUITECTO ==========
    
    onSearchArchitect(ev) {
        const value = ev.target.value;
        this.state.searchArchitectTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchArchitects();
        }, 300);
    }
    
    async searchArchitects() {
        try {
            const architects = await this.orm.call(
                "stock.quant",
                "get_architects",
                [],
                { search_term: this.state.searchArchitectTerm.trim() }
            );
            
            this.state.architects = architects;
        } catch (error) {
            console.error("Error buscando arquitectos:", error);
            this.notification.add("Error al buscar arquitectos", { type: "danger" });
        }
    }
    
    selectArchitect(architect) {
        this.state.selectedArchitectId = architect.id;
        this.state.selectedArchitectName = architect.display_name;
        this.state.showCreateArchitect = false;
    }
    
    toggleCreateArchitect() {
        this.state.showCreateArchitect = !this.state.showCreateArchitect;
        if (this.state.showCreateArchitect) {
            this.state.selectedArchitectId = null;
            this.state.selectedArchitectName = '';
        }
    }
    
    async createArchitect() {
        if (!this.state.newArchitectName.trim()) {
            this.notification.add("El nombre del arquitecto es requerido", { type: "warning" });
            return;
        }
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_architect",
                [],
                {
                    name: this.state.newArchitectName.trim(),
                    vat: this.state.newArchitectVat.trim(),
                    ref: this.state.newArchitectRef.trim()
                }
            );
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.success) {
                this.selectArchitect(result.architect);
                this.notification.add(`Arquitecto "${result.architect.name}" creado exitosamente`, { type: "success" });
                this.state.newArchitectName = '';
                this.state.newArchitectVat = '';
                this.state.newArchitectRef = '';
            }
        } catch (error) {
            console.error("Error creando arquitecto:", error);
            this.notification.add("Error al crear arquitecto", { type: "danger" });
        }
    }
    
    // ========== NAVEGACIÓN ==========
    
    nextStep() {
        if (this.state.currentStep === 1 && !this.state.selectedPartnerId) {
            this.notification.add("Debe seleccionar o crear un cliente", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 2 && !this.state.selectedProjectId) {
            this.notification.add("Debe seleccionar o crear un proyecto", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 3 && !this.state.selectedArchitectId) {
            this.notification.add("Debe seleccionar o crear un arquitecto", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 4) {
            const hasInvalidPrice = this.productIds.some(pid => {
                const price = this.state.productPrices[pid];
                return !price || price <= 0;
            });
            
            if (hasInvalidPrice) {
                this.notification.add("Debe configurar precios para todos los productos", { type: "warning" });
                return;
            }
        }
        
        if (this.state.currentStep < 5) {
            this.state.currentStep++;
        }
    }
    
    prevStep() {
        if (this.state.currentStep > 1) {
            this.state.currentStep--;
        }
    }
    
    // ========== CREAR HOLDS ==========
    
    async createHolds() {
        if (!this.state.selectedPartnerId || !this.state.selectedProjectId || !this.state.selectedArchitectId) {
            this.notification.add("Faltan datos requeridos", { type: "warning" });
            return;
        }
        
        this.state.isCreating = true;
        
        try {
            const result = await this.orm.call(
                "stock.quant",
                "create_holds_from_cart",
                [],
                {
                    partner_id: this.state.selectedPartnerId,
                    project_id: this.state.selectedProjectId,
                    architect_id: this.state.selectedArchitectId,
                    selected_lots: this.props.selectedLots,
                    notes: this.state.notas,
                    currency_code: this.state.selectedCurrency,
                    product_prices: this.state.productPrices
                }
            );
            
            // ✅ MANEJAR CASO DE AUTORIZACIÓN REQUERIDA
            if (result.needs_authorization) {
                this.notification.add(
                    `${result.message}\n\nPuede ver el estado en "Autorizaciones de Precio"`, 
                    { type: "warning", sticky: true }
                );
                this.props.onSuccess();
                this.props.close();
                return;
            }
            
            // ✅ CASO NORMAL: APARTADOS CREADOS
            if (result.success > 0) {
                this.notification.add(
                    `${result.success} lotes apartados correctamente`, 
                    { type: "success" }
                );
                this.props.onSuccess();
                this.props.close();
            }
            
            if (result.errors > 0) {
                let msg = `${result.errors} lotes no pudieron apartarse:\n`;
                result.failed.forEach(f => { 
                    msg += `\n• ${f.lot_name || 'Lote'}: ${f.error}`; 
                });
                this.notification.add(msg, { type: "warning", sticky: true });
            }
        } catch (error) {
            console.error("Error creando apartados:", error);
            this.notification.add("Error al crear apartados", { type: "danger" });
        } finally {
            this.state.isCreating = false;
        }
    }
    
    formatNumber(num) {
        return new Intl.NumberFormat('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num);
    }
}

HoldWizard.template = "inventory_shopping_cart.HoldWizard";
HoldWizard.components = { Dialog };
HoldWizard.props = {
    close: Function,
    selectedLots: Array,
    productGroups: Object,
    onSuccess: Function,
};