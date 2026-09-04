import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../static/src/utils/cart_selection.js', import.meta.url), 'utf8');
const policy = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const seller = {
    salesPermissionsLoaded: true, inventoryPermissionsLoaded: true,
    hasSalesPermissions: true, hasInventoryPermissions: true, isLocationMover: true,
};
const warehouse = { ...seller, hasSalesPermissions: false };
const free = { id: 1, lot_id: 24, lot_name: '20924-1', quantity: 10 };
const committed = { ...free, en_orden_venta: true, cart_block_reason: 'Comprometido en V/441' };

function controller(overrides = {}) {
    class Controller {}
    class ProductDetails {}
    const code = readFileSync(new URL('../static/src/components/cart_mixin/cart_mixin.js', import.meta.url), 'utf8');
    vm.runInNewContext(code.replace(/^import .*;\n/gm, ''), {
        ...policy, ProductDetails, console,
        registry: { category: () => ({ get: () => Controller }) },
        patch: Object.assign,
    });
    const instance = new Controller();
    const calls = [];
    Object.assign(instance, {
        cart: { ...seller, items: [] },
        state: { activeProductId: 7, manualInputValues: {} },
        orm: { call: async (...args) => { calls.push(args); return { success: true, quantity: 10 }; } },
        notification: { add() {} },
        updateCartSummary() {},
        getCurrentProductId: () => 7,
        getCurrentProductName: () => 'Test material',
        _forceRenderProduct() {},
        ...overrides,
    });
    return { instance, calls };
}

test('sales users cannot bypass sale/hold/workshop blocks with location mover permissions', () => {
    assert.equal(policy.canSelectBlocked(seller), false);
    for (const flag of ['en_orden_venta', 'tiene_hold', 'en_taller', 'is_transit', 'cart_blocked']) {
        assert.equal(policy.isCartDetailSelectable({ ...free, [flag]: true }, seller), false, flag);
    }
    assert.equal(policy.cartDetailBlockReason(committed), 'Comprometido en V/441');
});

test('permissions still loading never temporarily enable blocked selection', () => {
    for (const flag of ['salesPermissionsLoaded', 'inventoryPermissionsLoaded']) {
        assert.equal(policy.isCartDetailSelectable(committed, { ...warehouse, [flag]: false }), false);
    }
    assert.equal(policy.isCartDetailSelectable(committed, warehouse), true);
});

test('partial remainder is selectable but its committed summary is never selectable', () => {
    assert.equal(policy.isCartDetailSelectable({ ...free, is_available_row: true }, seller), true);
    for (const role of [seller, warehouse]) {
        assert.equal(policy.isCartDetailSelectable({ ...committed, id: '1-comprometido', is_committed_row: true }, role), false);
    }
});

test('select all excludes commitments and foreign carts', async () => {
    const { instance, calls } = controller({
        getProductDetails: () => [free, { ...committed, id: 2 }, { ...free, id: 3, tiene_hold: true },
            { ...free, id: 4, en_carrito: true, cart_info: { is_mine: false } }],
    });
    await instance.selectAllCurrentProduct();
    assert.equal(instance.cart.items.length, 1);
    assert.equal(instance.cart.items[0].id, 1);
    assert.equal(calls.filter(call => call[1] === 'add_to_cart').length, 1);
});

test('a previously selected lot can be removed after becoming committed', async () => {
    const { instance, calls } = controller();
    instance.cart.items.push(committed);
    await instance.toggleCartSelection(committed);
    assert.equal(instance.cart.items.length, 0);
    assert.equal(calls[0][1], 'remove_from_cart');
});

test('stale selection never enters cart while server validates and rejection refreshes the block', async () => {
    let resolve;
    const response = new Promise(done => { resolve = done; });
    const { instance } = controller({ orm: { call: () => response } });
    const detail = { ...free };
    const pending = instance.toggleCartSelection(detail);
    assert.equal(instance.cart.items.length, 0);
    resolve({ success: false, message: 'Comprometido en V/441',
        selection_state: { cart_blocked: true, cart_block_reason: 'Comprometido en V/441' } });
    await pending;
    assert.equal(instance.cart.items.length, 0);
    assert.equal(instance._isLotSelectable(detail), false);
});

test('successful server response inserts the lot once with validated quantity', async () => {
    const { instance } = controller();
    await instance.addOrUpdateCartItem(free, 10);
    await instance.addOrUpdateCartItem(free, 10);
    assert.equal(instance.cart.items.length, 1);
    assert.equal(instance.cart.items[0].quantity, 10);
});
