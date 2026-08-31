/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class SaleOrderWizard extends Component {
    setup() {
        // Medición SOM: mientras este diálogo esté abierto el tiempo
        // se atribuye a esta pantalla y no a la de atrás. Si el
        // módulo de medición no está instalado, nadie escucha y ya.
        onMounted(() => this.env.bus.trigger("SOM_ACTIVITY:SCREEN",
            { key: "cotizacion_captura", label: "Captura de orden de venta" }));
        onWillUnmount(() => this.env.bus.trigger("SOM_ACTIVITY:SCREEN", {}));

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
            
            // Embajador
            searchArchitectTerm: '',
            architects: [],
            selectedArchitectId: null,
            selectedArchitectName: '',
            showCreateArchitect: false,
            newArchitectName: '',
            newArchitectVat: '',
            newArchitectRef: '',
            
            // Empaques estándar (standard_pack_som): {pid: {default_pack_id, packs:[...]}}
            productPackOptions: {},
            productPacks: {},

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
            
            // Notas
            notas: '',
            applyTax: true,
            
            // UI
            isCreating: false,
            currentStep: 1,

            // === NUEVO: Info de autorizador ===
            isAuthorizer: false,
            lowPriceWarningProducts: [],
            showLowPriceWarning: false,
        });
        
        this.searchTimeout = null;
        this.loadPackOptions();
        this.loadPricelists().then(() => this._restoreDraft());
        this.checkAuthorizerStatus();

        // CAPTURA A PRUEBA DE REFRESH: el borrador se guarda en el
        // navegador; si la pagina se recarga a mitad de los 6 pasos, al
        // reabrir el wizard con el mismo material se restaura todo.
        this._draftSaver = () => this._saveDraft();
        window.addEventListener("beforeunload", this._draftSaver);
        onWillUnmount(() => {
            this._saveDraft();
            window.removeEventListener("beforeunload", this._draftSaver);
        });
    }

    get _draftKey() {
        const ids = [...this.productIds].sort((a, b) => a - b).join(",");
        return `som_so_wizard_draft_v1:${ids}`;
    }

    _saveDraft() {
        if (this._draftCleared) return;
        try {
            const st = this.state;
            const draft = {
                ts: Date.now(),
                currentStep: st.currentStep,
                selectedPartnerId: st.selectedPartnerId,
                selectedPartnerName: st.selectedPartnerName,
                selectedProjectId: st.selectedProjectId,
                selectedProjectName: st.selectedProjectName,
                selectedArchitectId: st.selectedArchitectId,
                selectedArchitectName: st.selectedArchitectName,
                selectedPricelistId: st.selectedPricelistId,
                selectedCurrency: st.selectedCurrency,
                productPrices: st.productPrices,
                productPacks: st.productPacks,
                selectedServices: st.selectedServices,
                notas: st.notas,
                applyTax: st.applyTax,
            };
            // Sin nada capturado no vale la pena guardar.
            if (!draft.selectedPartnerId && st.currentStep === 1) return;
            window.localStorage.setItem(this._draftKey, JSON.stringify(draft));
        } catch (e) {
            /* almacenamiento lleno o bloqueado: el borrador es cosmetico */
        }
    }

    _clearDraft() {
        this._draftCleared = true;
        try {
            window.localStorage.removeItem(this._draftKey);
        } catch (e) { /* nada */ }
    }

    _restoreDraft() {
        let draft = null;
        try {
            const raw = window.localStorage.getItem(this._draftKey);
            if (raw) draft = JSON.parse(raw);
        } catch (e) {
            return;
        }
        // 12 horas de vigencia: mas alla, la captura vieja estorba.
        if (!draft || !draft.ts || (Date.now() - draft.ts) > 12 * 3600 * 1000) {
            return;
        }
        const st = this.state;
        for (const key of ["currentStep", "selectedPartnerId",
                "selectedPartnerName", "selectedProjectId",
                "selectedProjectName", "selectedArchitectId",
                "selectedArchitectName", "selectedPricelistId",
                "selectedCurrency", "selectedServices", "notas",
                "applyTax"]) {
            if (draft[key] !== undefined && draft[key] !== null) {
                st[key] = draft[key];
            }
        }
        // Precios: solo los productos que siguen en esta seleccion, y sin
        // pisar opciones recien cargadas del servidor.
        if (draft.productPrices) {
            for (const pid of this.productIds) {
                if (draft.productPrices[pid] !== undefined) {
                    st.productPrices[pid] = draft.productPrices[pid];
                }
            }
        }
        if (draft.productPacks) {
            for (const pid of this.productIds) {
                if (draft.productPacks[pid] !== undefined) {
                    st.productPacks[pid] = draft.productPacks[pid];
                }
            }
        }
        this.notification.add(
            "Se restauro tu captura anterior de esta orden (cliente, precios "
            + "y notas). Revisa y continua donde ibas.",
            { type: "info", sticky: false });
    }

    async loadPackOptions() {
        // Productos que SOLO se venden por empaque: el selector vive en el
        // paso de precios. Defensivo: sin el módulo de empaques, vacío.
        try {
            const quantIds = [];
            for (const g of Object.values(this.props.productGroups || {})) {
                for (const lot of (g.lots || [])) quantIds.push(lot.id);
            }
            const opts = await this.orm.call(
                "sale.order", "get_cart_pack_options", [this.productIds, quantIds]);
            this.state.productPackOptions = opts || {};
            for (const [pid, opt] of Object.entries(this.state.productPackOptions)) {
                if (!this.state.productPacks[pid]) {
                    this.state.productPacks[pid] = opt.default_pack_id;
                }
            }
        } catch (e) {
            console.warn("[WIZARD] Sin opciones de empaque:", e);
            this.state.productPackOptions = {};
        }
    }

    // Ajuste cantidad↔empaque: cuántos empaques exactos caben en el
    // material seleccionado. exact=false => no es múltiplo (se bloquea el
    // avance con números accionables).
    packFit(productId) {
        const opt = this.state.productPackOptions[productId];
        if (!opt) return null;
        const packId = this.state.productPacks[productId] || opt.default_pack_id;
        const pack = (opt.packs || []).find((p) => p.id === packId) || opt.packs[0];
        if (!pack || !pack.qty_per_pack) return null;
        const group = this.props.productGroups[productId];
        const qty = group ? group.total_quantity : 0;
        const packs = qty / pack.qty_per_pack;
        const rounded = Math.round(packs);
        let exact = rounded > 0 && Math.abs(packs - rounded) <= 0.001;
        // LOTE COMPLETO siempre válido (cajas físicas aunque el empaque esté
        // redondeado): si cada lote del grupo se toma entero o en múltiplos,
        // cuadra. Las cantidades reales llegan en quant_full_qty.
        if (!exact && group && group.lots && group.lots.length) {
            const full = (opt.quant_full_qty || {});
            const ok = group.lots.every((lot) => {
                const f = parseFloat(full[String(lot.id)]);
                const q = parseFloat(lot.quantity) || 0;
                if (!isNaN(f) && f > 0 && Math.abs(q - f) <= 0.011) return true;
                const n = q / pack.qty_per_pack;
                return n >= 1 && Math.abs(n - Math.round(n)) <= 0.001;
            });
            if (ok) {
                return { exact: true, label: `= lote(s) completo(s), ${rounded || 1} empaque(s)` };
            }
        }
        if (exact) {
            return { exact, label: `= ${rounded} empaque(s) de ${pack.qty_per_pack}` };
        }
        const low = Math.max(Math.floor(packs), 0);
        const high = low + 1;
        return {
            exact,
            label: `⚠ ${qty.toFixed(2)} no es múltiplo de ${pack.qty_per_pack}: `
                + `ajusta a ${low}× (${(low * pack.qty_per_pack).toFixed(2)}) `
                + `o ${high}× (${(high * pack.qty_per_pack).toFixed(2)})`,
        };
    }

    async checkAuthorizerStatus() {
        try {
            const isAuth = await this.orm.call("res.users", "has_group", ["inventory_shopping_cart.group_price_authorizer"]);
            const isMayorista = await this.orm.call("res.users", "has_group", ["inventory_shopping_cart.group_seller_mayorista"]);
            this.state.isAuthorizer = isAuth || isMayorista;
        } catch (e) {
            this.state.isAuthorizer = false;
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
                
                // Nivel elegido con las opciones ANTERIORES (si el valor actual
                // coincidía con una de ellas). Se captura antes de pisarlas para
                // poder re-mapear el mismo nivel en la nueva divisa.
                const oldOptions = this.state.productPriceOptions[productId] || [];
                const currentValue = this.state.productPrices[productId];
                const oldLevel = (oldOptions.find(o => o.value === currentValue) || {}).level;

                this.state.productPriceOptions[productId] = prices;

                if (!prices.length) {
                    continue;
                }

                if (currentValue === undefined || currentValue === null || isNaN(currentValue)) {
                    // Primera carga: primer nivel visible.
                    this.state.productPrices[productId] = prices[0].value;
                } else if (oldOptions.length) {
                    // Recarga por cambio de divisa: mismo nivel en la nueva divisa.
                    // Un precio personalizado (sin nivel) no se arrastra entre
                    // divisas: cae al primer nivel para que el campo SIEMPRE
                    // refleje la divisa activa.
                    const match = oldLevel ? prices.find(o => o.level === oldLevel) : null;
                    this.state.productPrices[productId] = match ? match.value : prices[0].value;
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
        
        // No se resetean productPrices/productPriceOptions: loadAllProductPrices
        // re-mapea el nivel elegido a la nueva divisa (mismo nivel, nuevo monto).
        await this.loadAllProductPrices();
    }
    
    onPriceChange(productId, value) {
        const numValue = parseFloat(value);
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
        const changed = this.state.selectedPartnerId !== partner.id;
        this.state.selectedPartnerId = partner.id;
        this.state.selectedPartnerName = partner.display_name;
        this.state.showCreatePartner = false;
        if (changed) {
            // Proyectos son POR CLIENTE: al cambiar de cliente se limpia el
            // proyecto elegido y los resultados de búsqueda del anterior.
            this.state.selectedProjectId = null;
            this.state.selectedProjectName = '';
            this.state.projects = [];
        }
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
                {
                    search_term: this.state.searchProjectTerm.trim(),
                    partner_id: this.state.selectedPartnerId,
                }
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
                {
                    name: this.state.newProjectName.trim(),
                    partner_id: this.state.selectedPartnerId,
                }
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
    
    // ========== EMBAJADOR ==========
    
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
            console.error("Error buscando embajadores:", error);
            this.notification.add("Error al buscar embajadores", { type: "danger" });
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
            this.notification.add("El nombre del embajador es requerido", { type: "warning" });
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
                this.notification.add(`Embajador "${result.architect.name}" creado exitosamente`, { type: "success" });
                this.state.newArchitectName = '';
                this.state.newArchitectVat = '';
                this.state.newArchitectRef = '';
            }
        } catch (error) {
            console.error("Error creando embajador:", error);
            this.notification.add("Error al crear embajador", { type: "danger" });
        }
    }
    
    // ========== NAVEGACIÓN ==========
    
    /**
     * Detecta productos con precio por debajo del umbral autorizado por el rol
     * del usuario actual. El backend marca la opción umbral con is_threshold=true.
     */
    _detectLowPriceProducts() {
        const lowProducts = [];
        for (const productId of this.productIds) {
            const price = this.state.productPrices[productId];
            const options = this.state.productPriceOptions[productId] || [];
            const thresholdOption = options.find(o => o.is_threshold) ||
                options.find(o => o.level === 'medium');
            if (thresholdOption && price < (thresholdOption.value - 0.01)) {
                const group = this.props.productGroups[productId];
                lowProducts.push({
                    name: group ? group.name : `Producto ${productId}`,
                    price: price,
                    medium: thresholdOption.value,
                    threshold_label: thresholdOption.label,
                });
            }
        }
        return lowProducts;
    }

    nextStep() {
        if (this.state.currentStep === 1 && !this.state.selectedPartnerId) {
            this.notification.add("Debe seleccionar o crear un cliente", { type: "warning" });
            return;
        }
        // El proyecto es OPCIONAL: se puede avanzar sin elegirlo (la OV se
        // crea sin proyecto y puede asignarse después desde la orden).
        if (this.state.currentStep === 3 && !this.state.selectedArchitectId) {
            this.notification.add("Debe seleccionar o crear un embajador", { type: "warning" });
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

            // Empaques: todo producto con venta por empaque debe cuadrar en
            // múltiplos exactos ANTES de avanzar (el backend lo re-valida).
            for (const pid of Object.keys(this.state.productPackOptions)) {
                const fit = this.packFit(pid);
                if (fit && !fit.exact) {
                    const g = this.props.productGroups[pid];
                    this.notification.add(
                        `${g ? g.name : pid}: ${fit.label}`,
                        { type: "danger", sticky: true });
                    return;
                }
            }

            // === NUEVO: Detectar precios bajos para mostrar warning informativo al autorizador ===
            const lowProducts = this._detectLowPriceProducts();
            if (lowProducts.length > 0) {
                this.state.lowPriceWarningProducts = lowProducts;
                this.state.showLowPriceWarning = true;
            } else {
                this.state.lowPriceWarningProducts = [];
                this.state.showLowPriceWarning = false;
            }
        }
        
        if (this.state.currentStep < 6) {
            this.state.currentStep++;
        }
        this._saveDraft();
    }
    
    prevStep() {
        if (this.state.currentStep > 1) {
            this.state.currentStep--;
        }
        this._saveDraft();
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
                    standard_pack_id: this.state.productPacks[productId] || null,
                    price_unit: parseFloat(this.state.productPrices[productId]),
                    selected_lots: group.lots.map(lot => lot.id),
                    lots_breakdown: group.lots.map(lot => ({ 
                        id: lot.id, 
                        quantity: lot.quantity 
                    }))
                });
            }
            
            const services = this.state.selectedServices.map(s => ({
                product_id: s.product_id,
                quantity: s.quantity,
                price_unit: s.price_unit
            }));
            
            let finalNotes = this.state.notas || '';
            
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
            
            // MANEJAR CASO DE AUTORIZACIÓN REQUERIDA (solo para vendedores)
            if (result.needs_authorization) {
                this._clearDraft();
                this.notification.add(
                    `${result.message}\n\nPuede ver el estado en "Autorizaciones de Precio"`,
                    { type: "warning", sticky: true }
                );
                this.props.onSuccess();
                this.props.close();

                if (result.authorization_id) {
                    this.action.doAction({
                        type: 'ir.actions.act_window',
                        res_model: 'price.authorization',
                        res_id: result.authorization_id,
                        views: [[false, 'form']],
                        target: 'current',
                    });
                }
                return;
            }
            
            // CASO NORMAL: ORDEN CREADA
            if (result.success) {
                this._clearDraft();
                this.notification.add(`Orden ${result.order_name} creada exitosamente`, { type: "success" });
                this.props.onSuccess();
                this.props.close();
                
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