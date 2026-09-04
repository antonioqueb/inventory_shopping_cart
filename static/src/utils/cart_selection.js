/** @odoo-module **/

export function canSelectBlocked(cart = {}) {
    return !!(cart.salesPermissionsLoaded && cart.inventoryPermissionsLoaded
        && !cart.hasSalesPermissions
        && (cart.hasInventoryPermissions || cart.isLocationMover));
}

export function isCartDetailBlocked(detail) {
    return !!(detail.cart_blocked || detail.is_committed_row
        || detail.tiene_hold || detail.en_orden_venta || detail.en_taller || detail.is_transit
        || (detail.en_carrito && !detail.cart_info?.is_mine));
}

export function isCartDetailSelectable(detail, cart = {}) {
    // Las filas de resumen de una parcialidad no representan un quant.
    if (detail.is_committed_row || !Number.isInteger(detail.id) || detail.quantity <= 0) {
        return false;
    }
    return canSelectBlocked(cart) || !isCartDetailBlocked(detail);
}

export function cartDetailBlockReason(detail) {
    if (detail.cart_block_reason) return detail.cart_block_reason;
    if (detail.en_orden_venta) return "Lote comprometido en una orden de venta";
    if (detail.tiene_hold) return "Lote con apartado activo";
    if (detail.en_taller) return "Lote comprometido en taller / producción";
    if (detail.is_transit) return "Lote en tránsito";
    if (detail.en_carrito && !detail.cart_info?.is_mine) return "Lote en el carrito de otro usuario";
    return "Material no disponible";
}
