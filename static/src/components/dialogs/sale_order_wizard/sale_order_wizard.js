/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class SaleOrderWizard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        
        this.productIds = Object.keys(this.props.productGroups).map(id => parseInt(id));
        this.currentProductIndex = 0;
        
        this.state = useState({
            searchPartnerTerm: '',
            partners: [],
            selectedPartnerId: null,
            selectedPartnerName: '',
            showCreatePartner: false,
            newPartnerName: '',
            newPartnerVat: '',
            newPartnerRef: '',
            
            selectedCurrency: 'USD',
            pricelists: [],
            selectedPricelistId: null,
            
            productPrices: {},
            productPriceOptions: {},
            
            notas: '',
            applyTax: true,
            
            isCreating: false,
            currentStep: 1,
        });
        
        this.searchTimeout = null;
        this.loadPricelists();
    }
    
    get currentProductId() {
        return this.productIds[this.currentProductIndex];
    }
    
    get currentProductGroup() {
        return this.props.productGroups[this.currentProductId];
    }
    
    get isLastProduct() {
        return this.currentProductIndex === this.productIds.length - 1;
    }
    
    get isFirstProduct() {
        return this.currentProductIndex === 0;
    }
    
    get totalProducts() {
        return this.productIds.length;
    }
    
    nextProduct() {
        if (!this.isLastProduct) {
            if (!this.state.productPrices[this.currentProductId] || this.state.productPrices[this.currentProductId] <= 0) {
                this.notification.add("Debe configurar un precio válido para este producto", { type: "warning" });
                return;
            }
            
            this.currentProductIndex++;
            this.loadCurrentProductPrices();
        }
    }
    
    prevProduct() {
        if (!this.isFirstProduct) {
            this.currentProductIndex--;
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
            
            await this.loadCurrentProductPrices();
        } catch (error) {
            this.notification.add("Error al cargar listas de precios", { type: "warning" });
        }
    }
    
    async loadCurrentProductPrices() {
        try {
            const prices = await this.orm.call(
                "product.template",
                "get_custom_prices",
                [],
                {
                    product_id: this.currentProductId,
                    currency_code: this.state.selectedCurrency
                }
            );
            
            this.state.productPriceOptions[this.currentProductId] = prices;
            
            if (prices.length > 0 && !this.state.productPrices[this.currentProductId]) {
                this.state.productPrices[this.currentProductId] = prices[0].value;
            }
        } catch (error) {
            this.notification.add("Error al cargar precios", { type: "danger" });
        }
    }
    
    async onCurrencyChange(ev) {
        const pricelistName = ev.target.value;
        this.state.selectedCurrency = pricelistName;
        
        const pricelist = this.state.pricelists.find(p => p.name === pricelistName);
        if (pricelist) {
            this.state.selectedPricelistId = pricelist.id;
        }
        
        await this.loadCurrentProductPrices();
    }
    
    onPriceChange(value) {
        const numValue = parseFloat(value);
        const options = this.state.productPriceOptions[this.currentProductId] || [];
        
        if (options.length === 0) {
            this.state.productPrices[this.currentProductId] = numValue;
            return;
        }
        
        const minPrice = Math.min(...options.map(opt => opt.value));
        
        if (numValue < minPrice) {
            this.notification.add(
                `El precio no puede ser menor a ${this.formatNumber(minPrice)}`,
                { type: "warning" }
            );
            this.state.productPrices[this.currentProductId] = minPrice;
        } else {
            this.state.productPrices[this.currentProductId] = numValue;
        }
    }
    
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
            this.notification.add("Error al crear cliente", { type: "danger" });
        }
    }
    
    nextStep() {
        if (this.state.currentStep === 1 && !this.state.selectedPartnerId) {
            this.notification.add("Debe seleccionar o crear un cliente", { type: "warning" });
            return;
        }
        
        if (this.state.currentStep === 2) {
            const hasInvalidPrice = this.productIds.some(pid => {
                const price = this.state.productPrices[pid];
                const options = this.state.productPriceOptions[pid] || [];
                if (options.length === 0) return !price || price <= 0;
                const minPrice = Math.min(...options.map(opt => opt.value));
                return !price || price < minPrice;
            });
            
            if (hasInvalidPrice) {
                this.notification.add("Hay productos sin precio configurado", { type: "warning" });
                return;
            }
        }
        
        if (this.state.currentStep < 3) {
            this.state.currentStep++;
        }
    }
    
    prevStep() {
        if (this.state.currentStep > 1) {
            this.state.currentStep--;
            if (this.state.currentStep === 2) {
                this.currentProductIndex = 0;
            }
        }
    }
    
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
            
            let finalNotes = this.state.notas || '';
            if (!this.state.applyTax) {
                finalNotes += '\n\n⚠️ NOTA IMPORTANTE: El IVA se agregará posteriormente por cuestiones legales.';
            }
            
            const result = await this.orm.call("sale.order", "create_from_shopping_cart", [], {
                partner_id: this.state.selectedPartnerId,
                products: products,
                notes: finalNotes,
                pricelist_id: this.state.selectedPricelistId,
                apply_tax: this.state.applyTax
            });
            
            if (result.success) {
                this.notification.add(`Orden ${result.order_name} creada exitosamente`, { type: "success" });
                this.props.onSuccess();
                this.props.close();
            }
        } catch (error) {
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