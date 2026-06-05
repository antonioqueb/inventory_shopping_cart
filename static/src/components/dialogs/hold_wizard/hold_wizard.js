/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class HoldWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action"); 
        
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
            
            // Servicios
            searchServiceTerm: '',
            availableServices: [],
            selectedServices: [], 

            // === NUEVO: Materiales por Pedido (Sin Existencia) ===
            searchBackorderTerm: '',
            availableBackorderProducts: [],
            selectedBackorderItems: [], // {product_id, display_name, quantity, price_unit, uom_name}

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
        
        // Limpiar backorders si cambia la moneda (para obligar a actualizar precios)
        // Opcional: Podríamos recalcularlos
        this.state.selectedBackorderItems = [];
        await this.refreshSelectedServicePrices();
        
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
        if (this.searchTimeout) clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => { this.searchPartners(); }, 300);
    }
    
    async searchPartners() {
        try {
            const partners = await this.orm.call("stock.quant", "search_partners", [], { name: this.state.searchPartnerTerm.trim() });
            this.state.partners = partners;
        } catch (error) { this.notification.add("Error al buscar clientes", { type: "danger" }); }
    }
    
    selectPartner(partner) {
        this.state.selectedPartnerId = partner.id;
        this.state.selectedPartnerName = partner.display_name;
        this.state.showCreatePartner = false;
    }
    
    toggleCreatePartner() {
        this.state.showCreatePartner = !this.state.showCreatePartner;
        if (this.state.showCreatePartner) { this.state.selectedPartnerId = null; this.state.selectedPartnerName = ''; }
    }
    
    async createPartner() {
        if (!this.state.newPartnerName.trim()) { this.notification.add("El nombre es requerido", { type: "warning" }); return; }
        try {
            const result = await this.orm.call("stock.quant", "create_partner", [], {
                name: this.state.newPartnerName.trim(), vat: this.state.newPartnerVat.trim(), ref: this.state.newPartnerRef.trim()
            });
            if (result.success) { this.selectPartner(result.partner); this.notification.add("Cliente creado", { type: "success" }); }
        } catch (error) { this.notification.add("Error creando cliente", { type: "danger" }); }
    }

    // ========== PROYECTO ==========

    onSearchProject(ev) {
        const value = ev.target.value;
        this.state.searchProjectTerm = value;
        if (this.searchTimeout) clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => { this.searchProjects(); }, 300);
    }
    
    async searchProjects() {
        try {
            const projects = await this.orm.call("stock.quant", "get_projects", [], { search_term: this.state.searchProjectTerm.trim() });
            this.state.projects = projects;
        } catch (error) { this.notification.add("Error buscando proyectos", { type: "danger" }); }
    }
    
    selectProject(project) {
        this.state.selectedProjectId = project.id;
        this.state.selectedProjectName = project.name;
        this.state.showCreateProject = false;
    }
    
    toggleCreateProject() {
        this.state.showCreateProject = !this.state.showCreateProject;
        if (this.state.showCreateProject) { this.state.selectedProjectId = null; this.state.selectedProjectName = ''; }
    }
    
    async createProject() {
        if (!this.state.newProjectName.trim()) { this.notification.add("Nombre requerido", { type: "warning" }); return; }
        try {
            const result = await this.orm.call("stock.quant", "create_project", [], { name: this.state.newProjectName.trim() });
            if (result.success) { this.selectProject(result.project); this.notification.add("Proyecto creado", { type: "success" }); }
        } catch (error) { this.notification.add("Error creando proyecto", { type: "danger" }); }
    }

    // ========== ARQUITECTO ==========

    onSearchArchitect(ev) {
        const value = ev.target.value;
        this.state.searchArchitectTerm = value;
        if (this.searchTimeout) clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => { this.searchArchitects(); }, 300);
    }
    
    async searchArchitects() {
        try {
            const architects = await this.orm.call("stock.quant", "get_architects", [], { search_term: this.state.searchArchitectTerm.trim() });
            this.state.architects = architects;
        } catch (error) { this.notification.add("Error buscando arquitectos", { type: "danger" }); }
    }
    
    selectArchitect(architect) {
        this.state.selectedArchitectId = architect.id;
        this.state.selectedArchitectName = architect.display_name;
        this.state.showCreateArchitect = false;
    }
    
    toggleCreateArchitect() {
        this.state.showCreateArchitect = !this.state.showCreateArchitect;
        if (this.state.showCreateArchitect) { this.state.selectedArchitectId = null; this.state.selectedArchitectName = ''; }
    }
    
    async createArchitect() {
        if (!this.state.newArchitectName.trim()) { this.notification.add("Nombre requerido", { type: "warning" }); return; }
        try {
            const result = await this.orm.call("stock.quant", "create_architect", [], {
                name: this.state.newArchitectName.trim(), vat: this.state.newArchitectVat.trim(), ref: this.state.newArchitectRef.trim()
            });
            if (result.success) { this.selectArchitect(result.architect); this.notification.add("Arquitecto creado", { type: "success" }); }
        } catch (error) { this.notification.add("Error creando arquitecto", { type: "danger" }); }
    }

    // ========== SERVICIOS ==========
    
    onSearchService(ev) {
        const value = ev.target.value;
        this.state.searchServiceTerm = value;
        if (this.searchTimeout) clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => { this.searchServices(); }, 300);
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

            const enriched = [];
            for (const service of services) {
                const price = await this.getBackendProductPrice(service.id, 1);
                enriched.push({
                    ...service,
                    price_unit: price,
                });
            }

            this.state.availableServices = enriched;
        } catch (error) {
            this.notification.add("Error al buscar servicios", { type: "danger" });
        }
    }

    async getBackendProductPrice(productId, quantity = 1) {
        try {
            const result = await this.orm.call(
                "stock.quant",
                "get_sale_price_for_product",
                [],
                {
                    product_id: productId,
                    currency_code: this.state.selectedCurrency,
                    partner_id: this.state.selectedPartnerId,
                    quantity: quantity || 1,
                }
            );
            return result.price_unit || 0;
        } catch (error) {
            console.error("Error cargando precio de backend:", error);
            return 0;
        }
    }

    async refreshSelectedServicePrices() {
        for (const service of this.state.selectedServices) {
            service.price_unit = await this.getBackendProductPrice(
                service.product_id,
                service.quantity || 1
            );
        }
    }
    
    async addService(service) {
        const exists = this.state.selectedServices.find(s => s.product_id === service.id);
        if (exists) {
            this.notification.add("Este servicio ya fue agregado", { type: "warning" });
            return;
        }

        const priceUnit = service.price_unit || await this.getBackendProductPrice(service.id, 1);

        this.state.selectedServices.push({
            product_id: service.id,
            display_name: service.display_name,
            quantity: 1,
            price_unit: priceUnit,
            uom_name: service.uom_id[1]
        });
        this.state.searchServiceTerm = '';
        this.state.availableServices = [];
    }
    
    removeService(index) {
        this.state.selectedServices.splice(index, 1);
    }
    
    async updateServiceQuantity(index, value) {
        const qty = parseFloat(value) || 1;
        this.state.selectedServices[index].quantity = qty > 0 ? qty : 1;
        this.state.selectedServices[index].price_unit = await this.getBackendProductPrice(
            this.state.selectedServices[index].product_id,
            this.state.selectedServices[index].quantity
        );
    }
    
    updateServicePrice(index, value) {
        this.notification.add("El precio del servicio se carga desde la lista de precios y no se modifica manualmente.", { type: "info" });
    }
    
    getTotalServices() {
        return this.state.selectedServices.reduce((sum, s) => sum + (s.quantity * s.price_unit), 0);
    }

    // ========== NUEVO: MATERIALES POR PEDIDO (BACKORDER) ==========

    onSearchBackorder(ev) {
        const value = ev.target.value;
        this.state.searchBackorderTerm = value;
        if (this.searchTimeout) clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => { this.searchBackorderProducts(); }, 300);
    }

    async searchBackorderProducts() {
        try {
            // Buscamos productos que NO sean servicios (Almacenables o Consumibles)
            const products = await this.orm.searchRead(
                "product.product",
                [
                    ['type', '!=', 'service'], 
                    ['sale_ok', '=', true],
                    '|',
                    ['name', 'ilike', this.state.searchBackorderTerm.trim()],
                    ['default_code', 'ilike', this.state.searchBackorderTerm.trim()]
                ],
                ['id', 'display_name', 'list_price', 'uom_id', 'qty_available'],
                { limit: 20 }
            );
            this.state.availableBackorderProducts = products;
        } catch (error) {
            this.notification.add("Error buscando productos", { type: "danger" });
        }
    }

    async addBackorderItem(product) {
        const exists = this.state.selectedBackorderItems.find(b => b.product_id === product.id);
        if (exists) {
            this.notification.add("Este producto ya está en la lista de material adicional", { type: "warning" });
            return;
        }

        // Cargar el listado de precios del producto (escalera comercial) para que
        // el vendedor SELECCIONE el nivel, no escriba el precio libremente.
        let priceOptions = [];
        try {
            priceOptions = await this.orm.call(
                "product.template",
                "get_custom_prices",
                [],
                {
                    product_id: product.id,
                    currency_code: this.state.selectedCurrency,
                }
            );
        } catch (error) {
            console.error(`Error cargando precios para material adicional ${product.id}:`, error);
            priceOptions = [];
        }

        const defaultPrice = priceOptions.length > 0
            ? priceOptions[0].value
            : (product.list_price || 0);

        this.state.selectedBackorderItems.push({
            product_id: product.id,
            display_name: product.display_name,
            quantity: 1, // m² por defecto
            price_unit: defaultPrice,
            priceOptions: priceOptions,
            uom_name: product.uom_id[1]
        });

        this.state.searchBackorderTerm = '';
        this.state.availableBackorderProducts = [];
    }

    removeBackorderItem(index) {
        this.state.selectedBackorderItems.splice(index, 1);
    }

    updateBackorderQuantity(index, value) {
        const qty = parseFloat(value) || 1;
        this.state.selectedBackorderItems[index].quantity = qty > 0 ? qty : 1;
    }

    updateBackorderPrice(index, value) {
        const price = parseFloat(value) || 0;
        this.state.selectedBackorderItems[index].price_unit = price >= 0 ? price : 0;
    }

    getTotalBackorders() {
        return this.state.selectedBackorderItems.reduce((sum, b) => sum + (b.quantity * b.price_unit), 0);
    }
    
    // ========== NAVEGACIÓN ==========
    
    nextStep() {
        if (this.state.currentStep === 1 && !this.state.selectedPartnerId) {
            this.notification.add("Debe seleccionar un cliente", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 2 && !this.state.selectedProjectId) {
            this.notification.add("Debe seleccionar un proyecto", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 3 && !this.state.selectedArchitectId) {
            this.notification.add("Debe seleccionar un arquitecto", { type: "warning" });
            return;
        }
        if (this.state.currentStep === 4) {
            const hasInvalidPrice = this.productIds.some(pid => {
                const price = this.state.productPrices[pid];
                return !price || price <= 0;
            });
            if (hasInvalidPrice) {
                this.notification.add("Revise los precios de los lotes seleccionados", { type: "warning" });
                return;
            }
        }
        
        // Ahora hay 7 pasos: Cliente, Proyecto, Arq, Precios, Backorders, Servicios, Confirmar
        if (this.state.currentStep < 7) {
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
            const services = this.state.selectedServices.map(s => ({
                product_id: s.product_id,
                quantity: s.quantity,
                price_unit: s.price_unit
            }));

            // Agregar items de backorder (material adicional).
            // Saneamos cantidad/precio: un input vacío deja NaN en el estado y
            // JSON.stringify(NaN) -> null, que en el backend se vuelve 0.0.
            // Eso provocaba que la cantidad llegara en cero al apartado.
            const backorders = this.state.selectedBackorderItems.map(b => {
                const qty = Number(b.quantity);
                const price = Number(b.price_unit);
                return {
                    product_id: b.product_id,
                    quantity: Number.isFinite(qty) && qty > 0 ? qty : 1,
                    price_unit: Number.isFinite(price) && price >= 0 ? price : 0,
                };
            });

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
                    product_prices: this.state.productPrices,
                    services: services,
                    backorder_items: backorders // NUEVO CAMPO ENVIADO
                }
            );
            
            if (result.needs_authorization) {
                this.notification.add(`${result.message}`, { type: "warning", sticky: true });
                await this.props.onSuccess();
                this.props.close();
                return;
            }
            
            // Condición de éxito: Lotes creados OR Servicios/Backorders agregados a la orden
            const hasNonLotItems = (services.length > 0 || backorders.length > 0) && result.order_id;

            if (result.success > 0 || hasNonLotItems) {
                this.notification.add(
                    `${result.success} lotes y ${backorders.length} material adicional creados`,
                    { type: "success" }
                );

                // Limpiar carrito primero, sin recargar
                await this.props.onSuccess();

                // Cerrar wizard
                this.props.close();

                // Abrir la orden de reserva creada
                if (result.order_id) {
                    await this.action.doAction({
                        type: 'ir.actions.act_window',
                        res_model: 'stock.lot.hold.order',
                        res_id: result.order_id,
                        views: [[false, 'form']],
                        target: 'current',
                    });
                }

                return;
            }
            
            if (result.errors > 0) {
                let msg = `${result.errors} errores:\n`;
                result.failed.forEach(f => { msg += `\n• ${f.lot_name}: ${f.error}`; });
                this.notification.add(msg, { type: "warning", sticky: true });
            }
        } catch (error) {
            console.error("Error creando apartados:", error);
            this.notification.add("Error al crear apartados: " + error.message, { type: "danger" });
        } finally {
            if (this.state) this.state.isCreating = false;
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