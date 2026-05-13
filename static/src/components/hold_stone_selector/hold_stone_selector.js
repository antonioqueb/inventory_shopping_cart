/** @odoo-module **/

import { Component, useState, onWillUpdateProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

export class HoldStoneExpandButton extends Component {
    static template = "inventory_shopping_cart.HoldStoneExpandButton";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this._popupRoot = null;
        this._popupKeyHandler = null;
        this._styleNode = null;

        this.state = useState({
            selectedCount: this.getCurrentLotIds().length,
        });

        onWillUpdateProps(() => {
            this.state.selectedCount = this.getCurrentLotIds().length;
        });

        onWillUnmount(() => {
            this.destroyPopup();
            this._removeStyles();
        });
    }

    get selectedCount() {
        return this.state.selectedCount;
    }

    _escapeHtml(value) {
        if (value === null || value === undefined) {
            return "";
        }
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    _formatNumber(value) {
        const num = Number(value || 0);
        return num.toLocaleString("es-MX", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    _extractMany2OneId(value) {
        if (!value) {
            return false;
        }

        if (Array.isArray(value)) {
            return value[0] || false;
        }

        if (typeof value === "number") {
            return value;
        }

        if (typeof value === "object") {
            return value.id || value.resId || value.value || false;
        }

        return false;
    }

    _extractMany2OneName(value) {
        if (!value) {
            return "";
        }

        if (Array.isArray(value)) {
            return value[1] || "";
        }

        if (typeof value === "object") {
            return value.display_name || value.name || "";
        }

        return "";
    }

    getProductId() {
        return this._extractMany2OneId(this.props.record.data.product_id);
    }

    getProductName() {
        return this._extractMany2OneName(this.props.record.data.product_id);
    }

    getCurrentLotIds() {
        const rawLots = this.props.record.data.lot_ids;

        if (!rawLots) {
            return [];
        }

        if (Array.isArray(rawLots)) {
            return rawLots.filter((item) => typeof item === "number");
        }

        if (rawLots.currentIds) {
            return rawLots.currentIds;
        }

        if (rawLots.resIds) {
            return rawLots.resIds;
        }

        if (rawLots.records) {
            return rawLots.records
                .map((record) => record.resId || record.data?.id)
                .filter(Boolean);
        }

        return [];
    }

    _injectStyles() {
        if (this._styleNode) {
            return;
        }

        this._styleNode = document.createElement("style");
        this._styleNode.id = "inventory-shopping-cart-hold-stone-selector-style";
        this._styleNode.textContent = `
            .o_hold_stone_selector_btn {
                min-width: 38px;
                height: 30px;
                padding: 4px 8px;
                border-radius: 10px;
                font-weight: 700;
                line-height: 1;
            }

            .hold-stone-popup-overlay {
                position: fixed;
                inset: 0;
                z-index: 10500;
                display: flex;
                align-items: stretch;
                justify-content: stretch;
                padding: 16px;
                background: rgba(15, 23, 42, 0.58);
                backdrop-filter: blur(4px);
            }

            .hold-stone-popup {
                width: 100%;
                height: 100%;
                display: flex;
                flex-direction: column;
                overflow: hidden;
                border-radius: 22px;
                background: #fff;
                box-shadow: 0 30px 90px rgba(15, 23, 42, 0.36);
            }

            .hold-stone-popup-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 16px;
                padding: 16px 20px;
                border-bottom: 1px solid #d8dee4;
                background: linear-gradient(180deg, #ffffff, #f8fafc);
            }

            .hold-stone-popup-title {
                min-width: 0;
                color: #111827;
                font-size: 20px;
                font-weight: 800;
                line-height: 1.2;
            }

            .hold-stone-popup-subtitle {
                margin-top: 3px;
                color: #64748b;
                font-size: 12px;
                font-weight: 600;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .hold-stone-popup-actions {
                display: flex;
                align-items: center;
                gap: 8px;
                flex-wrap: wrap;
                justify-content: flex-end;
            }

            .hold-stone-badge {
                display: inline-flex;
                align-items: center;
                gap: 5px;
                min-height: 30px;
                padding: 6px 10px;
                border: 1px solid #d8dee4;
                border-radius: 999px;
                background: #f8fafc;
                color: #334155;
                font-size: 12px;
                font-weight: 800;
                white-space: nowrap;
            }

            .hold-stone-popup-filters {
                display: flex;
                align-items: flex-end;
                gap: 10px;
                flex-wrap: wrap;
                padding: 12px 16px;
                border-bottom: 1px solid #e5e7eb;
                background: #ffffff;
            }

            .hold-stone-filter {
                display: flex;
                flex-direction: column;
                gap: 4px;
            }

            .hold-stone-filter label {
                margin: 0;
                color: #64748b;
                font-size: 10px;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: .06em;
            }

            .hold-stone-filter input,
            .hold-stone-filter select {
                min-height: 32px;
                padding: 5px 8px;
                border: 1px solid #cbd5e1;
                border-radius: 9px;
                color: #111827;
                background: #fff;
                font-size: 12px;
                min-width: 110px;
            }

            .hold-stone-popup-body {
                flex: 1 1 auto;
                min-height: 0;
                overflow: auto;
                background: #fff;
            }

            .hold-stone-table {
                width: 100%;
                min-width: 1050px;
                border-collapse: separate;
                border-spacing: 0;
                font-size: 12px;
            }

            .hold-stone-table thead th {
                position: sticky;
                top: 0;
                z-index: 2;
                padding: 9px 8px;
                border-bottom: 1px solid #111827;
                background: #111827;
                color: #fff;
                font-size: 10px;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: .05em;
                white-space: nowrap;
            }

            .hold-stone-table tbody td {
                padding: 8px;
                border-bottom: 1px solid #edf2f7;
                vertical-align: middle;
                color: #1f2937;
                white-space: nowrap;
            }

            .hold-stone-table tbody tr {
                cursor: pointer;
                transition: background .14s ease;
            }

            .hold-stone-table tbody tr:hover {
                background: #f1f5f9;
            }

            .hold-stone-table tbody tr.is-selected {
                background: #eaf5ff;
                box-shadow: inset 4px 0 0 #2563eb;
            }

            .hold-stone-table .text-end {
                text-align: right;
            }

            .hold-stone-check {
                width: 18px;
                height: 18px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border: 2px solid #94a3b8;
                border-radius: 6px;
                background: #fff;
                color: #fff;
            }

            .hold-stone-check.checked {
                border-color: #2563eb;
                background: #2563eb;
            }

            .hold-stone-popup-footer {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                padding: 12px 16px;
                border-top: 1px solid #e5e7eb;
                background: #fff;
            }

            .hold-stone-empty {
                height: 260px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #64748b;
                font-weight: 700;
            }

            .hold-stone-footer-total {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 7px 11px;
                border-radius: 999px;
                background: #f1f5f9;
                color: #111827;
                font-size: 12px;
                font-weight: 800;
            }
        `;
        document.head.appendChild(this._styleNode);
    }

    _removeStyles() {
        if (this._styleNode) {
            this._styleNode.remove();
            this._styleNode = null;
        }
    }

    async openPopup(ev) {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }

        const productId = this.getProductId();

        if (!productId) {
            this.notification.add("Primero selecciona un producto en la línea.", {
                type: "warning",
            });
            return;
        }

        this._injectStyles();
        this.destroyPopup();

        this._popupRoot = document.createElement("div");
        this._popupRoot.className = "hold-stone-popup-root";
        document.body.appendChild(this._popupRoot);

        await this._renderPopup(productId);
    }

    async _loadQuants(productId, filters = {}) {
        const domain = [
            ["product_id", "=", productId],
            ["location_id.usage", "=", "internal"],
            ["quantity", ">", 0],
        ];

        if (filters.lotName) {
            domain.push(["lot_id.name", "ilike", filters.lotName]);
        }

        if (filters.locationName) {
            domain.push(["location_id.complete_name", "ilike", filters.locationName]);
        }

        let fields = [
            "id",
            "lot_id",
            "location_id",
            "quantity",
            "reserved_quantity",
        ];

        /*
         * Estos campos normalmente vienen de stock_lot_dimensions.
         * Si alguno no existe en la BD, hacemos fallback a campos mínimos.
         */
        const optionalFields = [
            "x_bloque",
            "x_atado",
            "x_alto",
            "x_ancho",
            "x_grosor",
            "x_tipo",
            "x_color",
        ];

        try {
            return await this.orm.searchRead(
                "stock.quant",
                domain,
                [...fields, ...optionalFields],
                {
                    limit: 500,
                    order: "lot_id",
                }
            );
        } catch (error) {
            console.warn("[HOLD STONE] Fallback sin campos extendidos:", error);
            return await this.orm.searchRead(
                "stock.quant",
                domain,
                fields,
                {
                    limit: 500,
                    order: "lot_id",
                }
            );
        }
    }

    _getLotIdFromQuant(quant) {
        return quant.lot_id ? quant.lot_id[0] : false;
    }

    _getLotNameFromQuant(quant) {
        return quant.lot_id ? quant.lot_id[1] : "";
    }

    _getLocationNameFromQuant(quant) {
        return quant.location_id ? quant.location_id[1] : "";
    }

    async _renderPopup(productId) {
        const currentLotIds = new Set(this.getCurrentLotIds());

        const state = {
            quants: [],
            selectedLotIds: new Set(currentLotIds),
            selectedQuantByLot: new Map(),
            filters: {
                lotName: "",
                locationName: "",
            },
            isLoading: true,
        };

        const productName = this.getProductName();
        const root = this._popupRoot;

        root.innerHTML = `
            <div class="hold-stone-popup-overlay">
                <div class="hold-stone-popup">
                    <div class="hold-stone-popup-header">
                        <div style="min-width:0;">
                            <div class="hold-stone-popup-title">
                                <i class="fa fa-th-large me-2"></i>
                                Seleccionar placas
                            </div>
                            <div class="hold-stone-popup-subtitle">
                                ${this._escapeHtml(productName || "Producto seleccionado")}
                            </div>
                        </div>

                        <div class="hold-stone-popup-actions">
                            <span class="hold-stone-badge">
                                <i class="fa fa-check-circle"></i>
                                <span id="hs-count">0</span> seleccionadas
                            </span>
                            <span class="hold-stone-badge">
                                <i class="fa fa-area-chart"></i>
                                <span id="hs-total">0.00</span> m²
                            </span>
                            <button type="button" class="btn btn-primary btn-sm" id="hs-confirm-top">
                                <i class="fa fa-check me-1"></i>
                                Aplicar
                            </button>
                            <button type="button" class="btn btn-light btn-sm" id="hs-close">
                                <i class="fa fa-times"></i>
                            </button>
                        </div>
                    </div>

                    <div class="hold-stone-popup-filters">
                        <div class="hold-stone-filter">
                            <label>Lote</label>
                            <input type="text" id="hs-filter-lot" placeholder="Buscar lote..."/>
                        </div>
                        <div class="hold-stone-filter">
                            <label>Ubicación</label>
                            <input type="text" id="hs-filter-location" placeholder="Buscar ubicación..."/>
                        </div>
                        <div style="display:flex; gap:8px; align-items:flex-end;">
                            <button type="button" class="btn btn-outline-secondary btn-sm" id="hs-refresh">
                                <i class="fa fa-refresh me-1"></i>
                                Buscar
                            </button>
                            <button type="button" class="btn btn-outline-secondary btn-sm" id="hs-clear-selection">
                                <i class="fa fa-square-o me-1"></i>
                                Limpiar selección
                            </button>
                        </div>
                    </div>

                    <div class="hold-stone-popup-body" id="hs-body">
                        <div class="hold-stone-empty">
                            <i class="fa fa-spinner fa-spin me-2"></i>
                            Cargando inventario...
                        </div>
                    </div>

                    <div class="hold-stone-popup-footer">
                        <span class="text-muted">
                            Clic sobre una fila para seleccionar o quitar una placa.
                        </span>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <span class="hold-stone-footer-total">
                                Total: <span id="hs-footer-total">0.00</span> m²
                            </span>
                            <button type="button" class="btn btn-light" id="hs-cancel">
                                Cancelar
                            </button>
                            <button type="button" class="btn btn-primary" id="hs-confirm-bottom">
                                <i class="fa fa-check me-1"></i>
                                Aplicar selección
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const body = root.querySelector("#hs-body");
        const countEl = root.querySelector("#hs-count");
        const totalEl = root.querySelector("#hs-total");
        const footerTotalEl = root.querySelector("#hs-footer-total");
        const filterLot = root.querySelector("#hs-filter-lot");
        const filterLocation = root.querySelector("#hs-filter-location");

        const updateTotals = () => {
            let total = 0;

            for (const quant of state.quants) {
                const lotId = this._getLotIdFromQuant(quant);
                if (lotId && state.selectedLotIds.has(lotId)) {
                    total += Number(quant.quantity || 0);
                }
            }

            countEl.textContent = String(state.selectedLotIds.size);
            totalEl.textContent = this._formatNumber(total);
            footerTotalEl.textContent = this._formatNumber(total);
        };

        const renderTable = () => {
            if (!state.quants.length) {
                body.innerHTML = `
                    <div class="hold-stone-empty">
                        <i class="fa fa-inbox me-2"></i>
                        No se encontraron placas disponibles.
                    </div>
                `;
                updateTotals();
                return;
            }

            let rows = "";

            for (const quant of state.quants) {
                const lotId = this._getLotIdFromQuant(quant);
                const lotName = this._getLotNameFromQuant(quant);
                const locationName = this._getLocationNameFromQuant(quant);
                const selected = lotId && state.selectedLotIds.has(lotId);

                if (selected) {
                    state.selectedQuantByLot.set(lotId, quant);
                }

                rows += `
                    <tr data-lot-id="${lotId || ""}"
                        data-quant-id="${quant.id}"
                        class="${selected ? "is-selected" : ""}">
                        <td style="width:42px;text-align:center;">
                            <span class="hold-stone-check ${selected ? "checked" : ""}">
                                ${selected ? '<i class="fa fa-check"></i>' : ""}
                            </span>
                        </td>
                        <td><strong>${this._escapeHtml(lotName || "-")}</strong></td>
                        <td>${this._escapeHtml(quant.x_bloque || "-")}</td>
                        <td>${this._escapeHtml(quant.x_atado || "-")}</td>
                        <td class="text-end">${this._escapeHtml(quant.x_alto || "-")}</td>
                        <td class="text-end">${this._escapeHtml(quant.x_ancho || "-")}</td>
                        <td class="text-end">${this._escapeHtml(quant.x_grosor || "-")}</td>
                        <td class="text-end"><strong>${this._formatNumber(quant.quantity)}</strong></td>
                        <td>${this._escapeHtml(quant.x_tipo || "Placa")}</td>
                        <td>${this._escapeHtml(quant.x_color || "-")}</td>
                        <td>${this._escapeHtml(locationName || "-")}</td>
                    </tr>
                `;
            }

            body.innerHTML = `
                <table class="hold-stone-table">
                    <thead>
                        <tr>
                            <th style="width:42px;text-align:center;">✓</th>
                            <th>Lote</th>
                            <th>Bloque</th>
                            <th>Atado</th>
                            <th class="text-end">Alto</th>
                            <th class="text-end">Ancho</th>
                            <th class="text-end">Esp.</th>
                            <th class="text-end">M²</th>
                            <th>Tipo</th>
                            <th>Color</th>
                            <th>Ubicación</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            `;

            body.querySelectorAll("tr[data-lot-id]").forEach((row) => {
                row.addEventListener("click", () => {
                    const lotId = parseInt(row.dataset.lotId || "0", 10);
                    const quantId = parseInt(row.dataset.quantId || "0", 10);

                    if (!lotId || !quantId) {
                        return;
                    }

                    const quant = state.quants.find((item) => item.id === quantId);

                    if (state.selectedLotIds.has(lotId)) {
                        state.selectedLotIds.delete(lotId);
                        state.selectedQuantByLot.delete(lotId);
                    } else {
                        state.selectedLotIds.add(lotId);
                        if (quant) {
                            state.selectedQuantByLot.set(lotId, quant);
                        }
                    }

                    renderTable();
                });
            });

            updateTotals();
        };

        const loadAndRender = async () => {
            state.filters.lotName = filterLot.value || "";
            state.filters.locationName = filterLocation.value || "";

            body.innerHTML = `
                <div class="hold-stone-empty">
                    <i class="fa fa-spinner fa-spin me-2"></i>
                    Cargando inventario...
                </div>
            `;

            try {
                state.quants = await this._loadQuants(productId, state.filters);

                for (const quant of state.quants) {
                    const lotId = this._getLotIdFromQuant(quant);
                    if (lotId && state.selectedLotIds.has(lotId)) {
                        state.selectedQuantByLot.set(lotId, quant);
                    }
                }

                renderTable();
            } catch (error) {
                console.error("[HOLD STONE] Error cargando inventario:", error);
                body.innerHTML = `
                    <div class="hold-stone-empty text-danger">
                        <i class="fa fa-exclamation-triangle me-2"></i>
                        Error al cargar inventario: ${this._escapeHtml(error.message || error)}
                    </div>
                `;
            }
        };

        const confirmSelection = async () => {
            const lotIds = Array.from(state.selectedLotIds);

            let totalQty = 0;
            let firstLot = false;
            let firstQuant = false;

            for (const lotId of lotIds) {
                const quant = state.selectedQuantByLot.get(lotId)
                    || state.quants.find((item) => this._getLotIdFromQuant(item) === lotId);

                if (!quant) {
                    continue;
                }

                if (!firstLot && quant.lot_id) {
                    firstLot = quant.lot_id;
                }

                if (!firstQuant) {
                    firstQuant = [
                        quant.id,
                        quant.lot_id ? quant.lot_id[1] : `Quant ${quant.id}`,
                    ];
                }

                totalQty += Number(quant.quantity || 0);
            }

            const updateVals = {
                lot_ids: [[6, 0, lotIds]],
                cantidad_m2: totalQty,
            };

            if (firstLot) {
                updateVals.lot_id = firstLot;
            } else {
                updateVals.lot_id = false;
            }

            if (firstQuant) {
                updateVals.quant_id = firstQuant;
            } else {
                updateVals.quant_id = false;
            }

            await this.props.record.update(updateVals);

            this.state.selectedCount = lotIds.length;
            this.destroyPopup();
        };

        root.querySelector("#hs-close").addEventListener("click", () => this.destroyPopup());
        root.querySelector("#hs-cancel").addEventListener("click", () => this.destroyPopup());
        root.querySelector("#hs-confirm-top").addEventListener("click", confirmSelection);
        root.querySelector("#hs-confirm-bottom").addEventListener("click", confirmSelection);

        root.querySelector("#hs-refresh").addEventListener("click", loadAndRender);

        root.querySelector("#hs-clear-selection").addEventListener("click", () => {
            state.selectedLotIds.clear();
            state.selectedQuantByLot.clear();
            renderTable();
        });

        const overlay = root.querySelector(".hold-stone-popup-overlay");
        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) {
                this.destroyPopup();
            }
        });

        const keyHandler = (event) => {
            if (event.key === "Escape") {
                this.destroyPopup();
            }
        };

        document.addEventListener("keydown", keyHandler);
        this._popupKeyHandler = keyHandler;

        let timeout = null;
        const debouncedLoad = () => {
            if (timeout) {
                clearTimeout(timeout);
            }
            timeout = setTimeout(loadAndRender, 350);
        };

        filterLot.addEventListener("input", debouncedLoad);
        filterLocation.addEventListener("input", debouncedLoad);

        await loadAndRender();
    }

    destroyPopup() {
        if (this._popupKeyHandler) {
            document.removeEventListener("keydown", this._popupKeyHandler);
            this._popupKeyHandler = null;
        }

        if (this._popupRoot) {
            this._popupRoot.remove();
            this._popupRoot = null;
        }
    }
}

export const holdStoneExpandButton = {
    component: HoldStoneExpandButton,
    displayName: "Selector de placas para apartado",
    supportedTypes: ["boolean"],
};

registry.category("fields").add("hold_stone_expand_button", holdStoneExpandButton);