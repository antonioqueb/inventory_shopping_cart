/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class SaleOrderWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        
        this.productIds = Object.keys(this.props.productGroups).map(id => parseInt(id));
        
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
            
            // Servicios
            searchServiceTerm: '',
            availableServices: [],
            selectedServices: [], // Array de {product_id, name, quantity, price_unit, display_name}
            
            // Notas
            notas: '',
            applyTax: true,
            
            // UI
            isCreating: false,
            currentStep: 1,
        });
        
        this.searchTimeout = null;
        this.loadPricelists();
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
        
        this.state.productPrices = {};
        this.state.productPriceOptions = {};
        
        await this.loadAllProductPrices();
    }
    
    onPriceChange(productId, value) {
        const numValue = parseFloat(value);
        
        // ✅ PERMITIR CUALQUIER PRECIO (incluso menor al mínimo)
        // El backend se encargará de crear la autorización si es necesario
        this.state.productPrices[productId] = numValue;
    }
    
    // ========== SERVICIOS ==========
    
    onSearchService(ev) {
        const value = ev.target.value;
        this.state.searchServiceTerm = value;
        
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        this.searchTimeout = setTimeout(() => {
            this.searchServices();
        }, 300);
    }
    
    async searchServices() {
        try {
            const services = await this.orm.searchRead(
                "product.product",
                [
                    ['type', '=', 'service'],
                    ['sale_ok', '=', true],
                    '|',
                    ['name', 'ilike', this.state.searchServiceTerm.trim()],
                    ['default_code', 'ilike', this.state.searchServiceTerm.trim()]
                ],
                ['id', 'display_name', 'list_price', 'uom_id'],
                { limit: 20 }
            );
            
            this.state.availableServices = services;
        } catch (error) {
            console.error("Error buscando servicios:", error);
            this.notification.add("Error al buscar servicios", { type: "danger" });
        }
    }
    
    addService(service) {
        const exists = this.state.selectedServices.find(s => s.product_id === service.id);
        if (exists) {
            this.notification.add("Este servicio ya fue agregado", { type: "warning" });
            return;
        }
        
        this.state.selectedServices.push({
            product_id: service.id,
            display_name: service.display_name,
            quantity: 1,
            price_unit: service.list_price,
            uom_name: service.uom_id[1]
        });
        
        this.state.searchServiceTerm = '';
        this.state.availableServices = [];
    }
    
    removeService(index) {
        this.state.selectedServices.splice(index, 1);
    }
    
    updateServiceQuantity(index, value) {
        const qty = parseFloat(value) || 1;
        this.state.selectedServices[index].quantity = qty > 0 ? qty : 1;
    }
    
    updateServicePrice(index, value) {
        const price = parseFloat(value) || 0;
        this.state.selectedServices[index].price_unit = price >= 0 ? price : 0;
    }
    
    getTotalServices() {
        return this.state.selectedServices.reduce((sum, s) => sum + (s.quantity * s.price_unit), 0);
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
        
        if (this.state.currentStep < 6) {
            this.state.currentStep++;
        }
    }
    
    prevStep() {
        if (this.state.currentStep > 1) {
            this.state.currentStep--;
        }
    }
    
    // ========== CREAR ORDEN ==========
    
    async createSaleOrder() {
        this.state.isCreating = true;
        
        try {
            const products = [];
            
            for (const [productId, group] of Object.entries(this.props.productGroups)) {
                products.push({
                    product_id: parseInt(productId),
                    quantity: group.total_quantity,
                    price_unit: parseFloat(this.state.productPrices[productId]),
                    selected_lots: group.lots.map(lot => lot.id)
                });
            }
            
            const services = this.state.selectedServices.map(s => ({
                product_id: s.product_id,
                quantity: s.quantity,
                price_unit: s.price_unit
            }));
            
            let finalNotes = this.state.notas || '';
            
            if (this.state.selectedProjectName) {
                finalNotes += `\n\n=== INFORMACIÓN DEL PROYECTO ===\n`;
                finalNotes += `Proyecto: ${this.state.selectedProjectName}\n`;
            }
            
            if (this.state.selectedArchitectName) {
                finalNotes += `Arquitecto: ${this.state.selectedArchitectName}\n`;
            }
            
            if (!this.state.applyTax) {
                finalNotes += '\n\n⚠️ NOTA IMPORTANTE: El IVA se agregará posteriormente por cuestiones legales.';
            }
            
            const result = await this.orm.call("sale.order", "create_from_shopping_cart", [], {
                partner_id: this.state.selectedPartnerId,
                products: products,
                services: services,
                notes: finalNotes,
                pricelist_id: this.state.selectedPricelistId,
                apply_tax: this.state.applyTax,
                project_id: this.state.selectedProjectId,
                architect_id: this.state.selectedArchitectId
            });
            
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
            
            // ✅ CASO NORMAL: ORDEN CREADA
            if (result.success) {
                this.notification.add(`Orden ${result.order_name} creada exitosamente`, { type: "success" });
                this.props.onSuccess();
                this.props.close();
                
                // Abrir la orden recién creada
                this.action.doAction({
                    type: 'ir.actions.act_window',
                    res_model: 'sale.order',
                    res_id: result.order_id,
                    views: [[false, 'form']],
                    target: 'current',
                });
            }
        } catch (error) {
            console.error("Error creando orden:", error);
            this.notification.add(error.message || "Error al crear orden", { type: "danger" });
        } finally {
            this.state.isCreating = false;
        }
    }
    
    formatNumber(num) {
        return new Intl.NumberFormat('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num);
    }
}

SaleOrderWizard.template = "inventory_shopping_cart.SaleOrderWizard";
SaleOrderWizard.components = { Dialog };
SaleOrderWizard.props = {
    close: Function,
    productGroups: Object,
    onSuccess: Function,
};