# ./__manifest__.py
{
    'name': 'Carrito de Compra para Inventario Visual',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Sistema de carrito de compra y apartado múltiple desde inventario visual',
    'author': 'Alphaqueb Consulting SAS',
    'website': 'https://alphaqueb.com',
    'depends': ['stock', 'sale_stock', 'inventory_visual_enhanced', 'stock_lot_dimensions', 'sale', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/email_templates.xml',
        'data/ir_cron.xml',  # <--- NUEVA LINEA AGREGADA
        'views/product_template_views.xml',
        'views/price_authorization_views.xml',

    ],
    'assets': {
        'web.assets_backend': [
            'inventory_shopping_cart/static/src/components/floating_bar/floating_bar.scss',
            'inventory_shopping_cart/static/src/components/dialogs/hold_wizard/hold_wizard.scss',
            'inventory_shopping_cart/static/src/components/dialogs/sale_order_wizard/sale_order_wizard.scss',
            'inventory_shopping_cart/static/src/components/dialogs/transfer_wizard/transfer_wizard.scss',
            
            'inventory_shopping_cart/static/src/components/cart_mixin/cart_mixin.js',
            'inventory_shopping_cart/static/src/components/floating_bar/floating_bar.js',
            'inventory_shopping_cart/static/src/components/dialogs/cart_dialog/cart_dialog.js',
            'inventory_shopping_cart/static/src/components/dialogs/hold_wizard/hold_wizard.js',
            'inventory_shopping_cart/static/src/components/dialogs/sale_order_wizard/sale_order_wizard.js',
            'inventory_shopping_cart/static/src/components/dialogs/transfer_wizard/transfer_wizard.js',
            
            'inventory_shopping_cart/static/src/patches/inventory_controller_patch.xml',
            'inventory_shopping_cart/static/src/components/floating_bar/floating_bar.xml',
            'inventory_shopping_cart/static/src/components/dialogs/cart_dialog/cart_dialog.xml',
            'inventory_shopping_cart/static/src/components/dialogs/hold_wizard/hold_wizard.xml',
            'inventory_shopping_cart/static/src/components/dialogs/sale_order_wizard/sale_order_wizard.xml',
            'inventory_shopping_cart/static/src/components/dialogs/transfer_wizard/transfer_wizard.xml',
            'inventory_shopping_cart/static/src/components/dialogs/label_wizard/label_wizard.scss',
            'inventory_shopping_cart/static/src/components/dialogs/label_wizard/label_wizard.js',
            'inventory_shopping_cart/static/src/components/dialogs/label_wizard/label_wizard.xml',
            
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}