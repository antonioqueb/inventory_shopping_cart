# ./models/stock_quant.py
# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import math

_logger = logging.getLogger(__name__)


# Logo SOM en ZPL (^GFA 1-bit, recortado del PNG oficial, rotado 90°
# como el texto ^A0R de las etiquetas). Se posiciona con ^FO al usarlo.
# Variante SIN rotar para la banda superior del canto/lomo (^A0N),
# 160 dots de ancho — el tamaño del texto "( SOM )" que sustituye.
SOM_LOGO_CANTO_ZPL = "^GFA,1020,1020,20,0000000000000000000000000000000000000000000000FFF0000000FFE00000F000001E00000000000003FFFE000007FFF80001F800001F00000000000007FFFF00000FFFFE0001F800003F0000000000000F800F80003F003F0001FC00003F0000000000001E0007C0007C000F8001FC00007F0000000000001C0003C000780007C001DC0000770000000000003C0001E000F00003C001DE0000E70000000000003C0000E001E00001E001CE0000E7000000000000380000E001C00000E001CF0000E7000000000000380000E003C00000F001CF0001C70000000000003C000000038000007001C70001C70000000000001C000000038000007001C78003870000000000001E000000078000007801C38003870000000000000F800000078000007801C3C007070000000000000FF00000070000007801C1C0070700000000000003FFF000070000003801C1C0070700000000000000FFFF00070000003801C1E00E07000000000000001FFFC0070000003801C0E00E0700000000000000001FE0070000007801C0F01C07000000000000000001E0078000007801C0701C07000000000000000000F0078000007001C070380700000000000000000070038000007001C07838070000000000007000007003800000F001C03838070000000000007000007003C00000F001C03C70070000000000007800007001C00001E001C01C70070000000000007800007001E00001E001C01CE0070000000000003C00007000F00003C001C00EE0070000000000003E0000F000F800078001C00FC0070000000000001F0001E0007C000F8001C00FC0070000000000000FC003C0003F003F0001C007C00700000000000007FC3F80001FE1FC0001C007800700000000000003FFFF000007FFF80001C0038007000000000000007FFC000001FFE00001C00300070000000000000007C00000001E00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000FC30000000000000000000000000000000000001864800010000200000200040000010000000400372C03021601C600C186081401306186040184702596048D1B1362112246362C06C8918D186244D8249188889113021100423244044811099040C4C0279048889110C211034230440448D108104244302C94C4891110221122623024044891881044440824A3870F1111C310E1C31C3C0408F0C70003C47010600008000000000000000000000000000000000DC0000000000000000000000000000000000000070"

SOM_LOGO_ZPL = "^GFA,8118,8118,18,00000000000000000000000000000000000000000000000000000000000000000000000000601F00000000000000000000000000000000E03FC0000000000000000000000000000001E079C0000000000000000000000000000001C060E000000000000000000000000000000380E0E000000000000000000000000000000380E06000000000000000000000000000000300C06000000000000000000000000000000301C06000000000000000000000000000000381C0600000000000000000000000000000038380E00000000000000000000000000000018380C0000000000000000000000000000001EF03C0000000000000000000000000000000FF03800000000000000000000000000000007C01000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000F00000000000000000000000000000000007FE000000000000000000000000000000000FFF000000000000000000000000000000001E07800000000000000000000000000000001803800000000000000000000000000000003801800000000000000000000000000000003000C00000000000000000000000000000003000C00000000000000000000000000000003000C00000000000000000000000000000003801800000000000000000000000000000001803800000000000000000000000000000001E0F800000000000000000000000000000000FFF0000000000000000000000000000000007FC00000000000000000000000000000000006000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000007FFFF80000000000000000000000000000007FFFF800000000000000000000000000000001FFF00000000000003E000000000000000001C030000000000003FE000000000000000001801800000000000FFE000000000000000003001800000000003FFE00000000000000000300180000000000FFFE00000000FF8000000300180000000003FFFE0000000FFFF800000300180000000007FFFE0000007FFFFE0000038038000000000FFFFE000000FFFFFF800001F1F0000000001FFFFE000003FFFFFFE00000FFE0000000007FFFFC000007FFFFFFF000003F80000000007FFF8000000FFFFFFFF80000000000000000FFFE0000001FFFFFFFFC0000000000000001FFF80000001FFFFFFFFE0000000000000003FFE00000003FFFE3FFFF0000000000000007FFC00000007FFE001FFF0000000000000007FF800000007FF80007FF800000000000000FFE00000000FFE00003FFC00000000000000FFE00000000FFC00000FFC00000000000001FFC00000001FF800000FFE003FFFFE000001FF800000001FF8000007FE003FFFFE000003FF000000003FF0000003FE00000700000003FF000000003FE0000003FF00000380000007FE000000007FE0000001FF00000180000007FE000000007FC0000001FF00000180000007FC000000007FC0000000FF8000018000000FFC000000007FC0000000FF8000018000000FF800000000FF80000000FF8000038000000FF800000000FF800000007F80000F8000000FF800000000FF800000007FC03FFF0000001FF000000000FF800000007FC03FFE0000001FF000000001FF800000007FC000000000001FF000000001FF000000007FC000000000001FF000000001FF000000007FC000000000001FF000000001FF000000003FC000000000001FE000000001FF000000003FC000000000003FE000000001FF000000003FC000000000003FE000000001FF000000003FC000000000003FE000000003FE000000003FC000000000003FE000000003FE000000003FC000000000003FE000000003FE000000003FC03FFF8E00003FE000000003FE000000003FC03FFF8E00003FE000000003FE000000003FC000000000003FE000000003FE000000003FC000000000003FE000000003FE000000003FC000000000003FE000000003FE000000007FC000000000003FE000000003FE000000007FC000000000003FE000000003FC000000007FC000000000003FE000000007FC000000007FC000000000001FE000000007FC000000007FC000000000001FE000000007FC00000000FF800C1E0000001FE000000007FC00000000FF801C3F0000001FE000000007FC00000000FF801C7B8000001FF000000007FC00000000FF8038718000001FF000000007FC00000001FF0030618000001FF000000007F800000001FF003060C000000FF00000000FF800000003FF003061C000000FF80000000FF800000003FF0030E18000000FF80000000FF800000007FE0038E180000007F80000000FF80000000FFE001DC380000007FC0000001FF80000001FFC001FC700000007FC0000001FF00000003FFC000F8200000003FE0000003FF00000007FF800000000000003FF0000003FF0000000FFF800000000000001FF8000007FE0000003FFF000000000000001FFC000007FE000000FFFE000000000000000FFE00000FFE000007FFFC000000000000000FFF00003FFC00007FFFFC0000000000000007FFC0007FFC00007FFFF80000000000000003FFF803FFF800007FFFE00000001800000001FFFFFFFFF000007FFFC00000001800000000FFFFFFFFF000007FFF800001FFFFC00000007FFFFFFFE000007FFE000003FFFFE00000003FFFFFFFC000007FF80000038018000000001FFFFFFF8000007FE000000300180000000007FFFFFE0000007F0000000300180000000001FFFFF80000000000000003001800000000007FFFE000000000000000000000000000000001FC000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001FFF860000000000000000000000000000003FFF8E0000000000000000000000000000003FFF8E00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001F80000000000000000000000000000000007FE000000000000000000000000000000000FFF000000000000000000000000000000001C03800000000000000000000000000000003801800000000000000000000000000000003801800000000000000000000000000000003001800000000000000003FF00000000000030018000000000000001FFFFFE00000000003801800000000000001FFFFFFFE000000000380380000000000000FFFFFFFFFC000000001C0780000000000007FFFFFFFFFF000000001E070000000000001FFFFFFFFFFFC00000000C060000000000007FFFFFFFFFFFF00000000000000000000001FFFFFFFFFFFFFC0000000000000000000003FFFFFFFFFFFFFE000000000000000000000FFFFFFFFFFFFFFF800000000000000000001FFFFFE0003FFFFFC00000000000000000003FFFFC000001FFFFE0000000000000000000FFFFE00000003FFFF0000000000000000001FFFF0000000007FFF800000F000000000003FFFC0000000001FFFC00001FC30000000007FFF000000000007FFE00001FC7000000000FFFC000000000003FFF000038E3800000000FFF8000000000000FFF80003061800000001FFF00000000000007FFC0003061800000003FFC00000000000003FFC0003061800000007FF800000000000001FFE0003061800000007FF000000000000000FFF000186180000000FFE0000000000000007FF0001C7180000000FFE0000000000000003FF8000F7780000001FFC0000000000000001FF8003FFF00000001FF80000000000000000FFC003FFE00000003FF00000000000000000FFC00000000000003FF000000000000000007FE00000000000007FE000000000000000007FE00000000000007FE000000000000000003FF0000000000000FFC000000000000000003FF0000000000000FFC000000000000000001FF0000000000000FF8000000000000000001FF0000000000000FF8000000000000000000FF8000018000001FF0000000000000000000FF8000018000001FF0000000000000000000FF800FFFFC00001FF00000000000000000007F801FFFFC00001FF00000000000000000007FC03FFFFC00001FE00000000000000000007FC030018000003FE00000000000000000007FC030018000003FE00000000000000000007FC030018000003FE00000000000000000003FC000000000003FE00000000000000000003FC000000000003FE00000000000000000003FC000000000003FE00000000000000000003FC000000000003FE00000000000000000003FC000000000003FE00000000000000000003FC000000000003FE00000000000000000003FC000000000003FE00000000000000000003FC003FC0000003FE00000000000000000003FC00FFE0000003FE00000000000000000003FC01FFF0000001FE00000000000000000007FC01C638000001FE00000000000000000007FC038618000001FF00000000000000000007FC030618000001FF00000000000000000007FC03060C000001FF00000000000000000007FC030618000001FF8000000000000000000FF8030618000000FF8000000000000000000FF8038638000000FF8000000000000000000FF801C7F0000000FFC000000000000000001FF800C7E00000007FC000000000000000001FF00047C00000007FE000000000000000003FF00000000000003FE000000000000000003FF00000000000003FF000000000000000007FE00000000000003FF800000000000000007FE00000000000001FF80000000000000000FFC00000000000001FFC0000000000000001FFC00000000000000FFE0000000000000003FF8000000000000007FF0000000000000003FF80001F8000000007FF8000000000000007FF0000FFE000000003FFC00000000000000FFF0001FFF000000001FFE00000000000001FFE0001C03800000000FFF00000000000007FFC0003801800000000FFFC000000000000FFFC00030018000000007FFE000000000003FFF80003000C000000003FFF800000000007FFF000030018000000001FFFE0000000001FFFE000038018000000000FFFF8000000007FFFC00001C0300000000007FFFF00000003FFFF800001FFF00000000001FFFFE000001FFFFF000003FFFFE000000000FFFFFF0003FFFFFC000003FFFFE0000000007FFFFFFFFFFFFFF8000000000000000000001FFFFFFFFFFFFFF00000000000000000000007FFFFFFFFFFFFC00000000000000000000003FFFFFFFFFFFF000000000000000000000000FFFFFFFFFFFC0000000000000000000000001FFFFFFFFFF000000000000000000000000003FFFFFFFF80000000000000000000000000007FFFFFFC000000000000000000000000000003FFFF800000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001FFF800000000000000000000000000000003FFF800000000000000000000000000000003FFF800000000000000000000000000000000007000000000000000000000000000000000001800000000000000000000000000000000001800000000000000000000000000000000001800000000000000000000000000000000001800000000000000000000000000000000001800000000000000000000000000000000003800000000000000000000000000000003FFF800000000000000000000000000000003FFF000000000000000000000000000000003FFE0000000000000000000000000000000000030000000000000000000000000000000000018000000000000000000000000000000000018000000000000000000000000000000000018000000000000000000000000000000000018000000FFFFFFFFFFFFFFFFFFFFFFF0000018000000FFFFFFFFFFFFFFFFFFFFFFF0000038000000FFFFFFFFFFFFFFFFFFFFFFF003FFF0000000FFFFFFFFFFFFFFFFFFFFFFF003FFE0000000FFFFFFFFFFFFFFFFFFFFFFF001FF00000000FFFFFFFFFFFFFFFFFFFFFFF0000000000000FFFFFFFFFFFFFFFFFFFFFFF0000000000000FFFFFFFFFFFFFFFFFFFFFFF00000000000007FFFFFFFFFFFFFFFFFFE7FF0000000000000000000000000000000007FF000000000000000000000000000000003FFF00000000000000000000000000000000FFFF00000000000000000000000000000007FFFF000F000000000000000000000000001FFFFF001FC7000000000000000000000000FFFFFF001DC7000000000000000000000003FFFFFC0038E380000000000000000000001FFFFFF000306180000000000000000000007FFFFF800030618000000000000000000001FFFFFE00003061800000000000000000000FFFFFF000003061800000000000000000003FFFFFC00000186180000000000000000001FFFFFE0000001C3180000000000000000007FFFFF80000000FFF8000000000000000003FFFFFC00000003FFF000000000000000000FFFFFF000000003FFC000000000000000003FFFFF800000000000000000000000000001FFFFFE000000000000000000000000000007FFFFF000000000000000000000000000003FFFFFC00000000000000000000000000000FFFFFE000000000000000000000000000003FFFFF800000000000000000000000000001FFFFFC000000000000000000000000000007FFFFF000000000000000018000000000003FFFFFC00000000000000001800000000000FFFFFE000000000000000FFFFC0000000007FFFFF8000000000000001FFFFE000000001FFFFFC0000000000000003FFDFC000000007FFFFF000000000000000030018000000003FFFFF800000000000000003001800000000FFFFFE000000000000000003001800000007FFFFF000000000000000000000000000001FFFFFC000000000000000000000000000007FFFFE000000000000000000000000000000FFFFF8000000000000000000000000000000FFFFC0000000000000000000000000000000FFFF00000000000000000000000000000000FFFF00000000000000000000000000000000FFFFE0000000000000000000007FC00000007FFFF800000000000000000000FFF00000000FFFFF00000000000000000001F6F000000003FFFFC0000000000000000001C63800000000FFFFF00000000000000000038618000000001FFFFE00000000000000000306080000000007FFFF800000000000000003060C0000000001FFFFE00000000000000003061800000000003FFFFC0000000000000003861800000000000FFFFF00000000000000038638000000000003FFFFC000000000000001C7F00000000000007FFFF800000000000000C7E00000000000001FFFFE0000000000000047C000000000000007FFFF80000000000000000000000000000000FFFFF00000000000000000000000000000003FFFFC0000000000000000000000000000000FFFFF00000000000000000000000000000001FFFFE00000000000000000000000000000007FFFF80000000000000000000000000000001FFFFE00000000000000000000000000000003FFFFC0000000000000000000000000000000FFFFF000000003FFF80000000000000000003FFFFC00000003FFF800000000000000000007FFFF80000000007000000000000000000001FFFFE00000000038000000000000000000007FFFF80000000018000000000000000000000FFFFF00000000180000000000000000000003FFFFC0000000180000000000000000000000FFFFF00000001800000000000000000000001FFFFE00000008000000000000000000000007FFFF80000000000000000000000000000001FFFFE00000000000000000000000000000003FFFF00000000000000000000000000000000FFFF000000000000000000000000000000003FFF0000000000000000000000000000000007FF00000000000007FFFFFFFFFFFFFFFFFFFFFF0000000000000FFFFFFFFFFFFFFFFFFFFFFF0000000000000FFFFFFFFFFFFFFFFFFFFFFF003FFF8E00000FFFFFFFFFFFFFFFFFFFFFFF003FFF8E00000FFFFFFFFFFFFFFFFFFFFFFF0000000000000FFFFFFFFFFFFFFFFFFFFFFF0000000000000FFFFFFFFFFFFFFFFFFFFFFF0000000000000FFFFFFFFFFFFFFFFFFFFFFF0000000000000FFFFFFFFFFFFFFFFFFFFFFF00000000000007FFFFFFFFFFFFFFFFFFFFFF000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000700000000000000000000000000000000000F82000000000000000000000000000000001FC70000000000000000000000000000000038C3800000000000000000000000000000003061800000000000000000000000000000003061800000000000000000000000000000003061800000000000000000000000000000003061800000000000000000000000000000003861800000000000000000000000000000001861800000000000000000000000000000000E33800000000000000000000000000000003FFF000000000000000000000000000000003FFE000000000000000000000000000000003000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001FFFFC0000000000000000000000000000003FFFFE0000000000000000000000000000003FFFFE0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000C1F000000000000000000000000000000001C3F800000000000000000000000000000001C73800000000000000000000000000000003871800000000000000000000000000000003061800000000000000000000000000000003060C00000000000000000000000000000003061C000000000000000000000000000000030E18000000000000000000000000000000038E1800000000000000000000000000000001DC7800000000000000000000000000000001FC7000000000000000000000000000000000F820000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001FFC000000000000000000000000000000007FFF00000000000000000000000000000001FFFFC0000000000000000000000000000003F007E00000000000000000000000000000078001F000000000000000000000000000000F00007800000000000000000000000000001E00003800000000000000000000000000001C00001C0000000000000000000000000000387FFF1C0000000000000000000000000000387FFF0E0000000000000000000000000000307FFF0E00000000000000000000000000007001C70E00000000000000000000000000007001C70600000000000000000000000000007001C70700000000000000000000000000007001C70700000000000000000000000000007001C70700000000000000000000000000007001C70600000000000000000000000000003003C70E0000000000000000000000000000383FFE0E0000000000000000000000000000387FFE0E00000000000000000000000000001C783C1C00000000000000000000000000001E40003C00000000000000000000000000000F0000380000000000000000000000000000078000F8000000000000000000000000000003E001F0000000000000000000000000000001FC0FE0000000000000000000000000000000FFFF800000000000000000000000000000003FFE0000000000000000000000000000000003E0000000000000000000000000000000"


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    # ═══════════════════════════════════════════════════════════════════
    # ESTADO "EN CARRITO" para el Inventario Visual: cada quant se anota
    # con el carrito activo que lo retiene (de cualquier vendedor), igual
    # que los estados de hold / orden de venta / taller.
    # ═══════════════════════════════════════════════════════════════════
    @api.model
    def get_quant_details(self, quant_ids=None):
        res = super().get_quant_details(quant_ids=quant_ids)
        if not res:
            return res
        try:
            Cart = self.env['shopping.cart'].sudo()
            Cart._gc_expired()
            entries = Cart.search([
                ('quant_id', 'in', [d.get('id') for d in res if d.get('id')]),
            ])
            by_quant = {}
            by_lot = {}
            for e in entries:
                by_quant[e.quant_id.id] = e
                if e.lot_id:
                    by_lot.setdefault(e.lot_id, e)
            for d in res:
                entry = by_quant.get(d.get('id'))
                if not entry and d.get('lot_id'):
                    # El mismo LOTE puede estar en carrito vía otro quant
                    # (otra ubicación): el estado aplica al lote completo.
                    entry = by_lot.get(d.get('lot_id'))
                if entry:
                    added_local = fields.Datetime.context_timestamp(
                        self, entry.added_at or entry.create_date)
                    activity_local = fields.Datetime.context_timestamp(
                        self, entry.write_date or entry.create_date)
                    d['en_carrito'] = True
                    d['cart_info'] = {
                        'user_id': entry.user_id.id,
                        'user_name': entry.user_id.name,
                        'is_mine': entry.user_id.id == self.env.uid,
                        'added_at': added_local.strftime('%d/%m/%Y %H:%M'),
                        'last_activity': activity_local.strftime('%d/%m/%Y %H:%M'),
                        'hours_left': entry._som_hours_left(),
                        'quantity': entry.quantity,
                        'ttl_hours': Cart.CART_TTL_HOURS,
                    }
                else:
                    d['en_carrito'] = False
                    d['cart_info'] = None
        except Exception:
            _logger.exception('[CART STATE] No se pudo anotar el estado de carrito.')
        return res

    @api.model
    def get_current_user_info(self):
        """Obtener información del usuario actual"""
        return {
            'id': self.env.user.id,
            'name': self.env.user.name
        }

    @api.model
    def _get_pricelist_for_currency(self, currency_code='USD'):
        currency_code = currency_code or 'USD'
        return self.env['product.pricelist'].search([
            ('name', '=', currency_code),
        ], limit=1)

    @api.model
    def _compute_product_sale_price(self, product, currency_code='USD', partner_id=None, quantity=1.0):
        """
        Calcula un precio de venta de catálogo/pricelist para productos no sujetos
        a la escalera especial de mármol, principalmente servicios.

        No confía en el valor enviado por el frontend.
        """
        quantity = float(quantity or 1.0)
        if quantity <= 0:
            quantity = 1.0

        partner = self.env['res.partner'].browse(partner_id) if partner_id else self.env['res.partner']
        pricelist = self._get_pricelist_for_currency(currency_code)
        price = 0.0

        if product and product.exists() and pricelist:
            try:
                price = pricelist._get_product_price(product, quantity, partner=partner if partner else False)
            except TypeError:
                try:
                    price = pricelist.get_product_price(product, quantity, partner if partner else False)
                except Exception:
                    price = 0.0
            except Exception:
                price = 0.0

        if price <= 0 and product and product.exists():
            price = getattr(product, 'lst_price', 0.0) or getattr(product, 'list_price', 0.0) or 0.0

            # Si no hubo lista de precios y la moneda solicitada es distinta a la de compañía,
            # convertir el precio base de la compañía a la moneda solicitada.
            currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
            company_currency = self.env.company.currency_id
            if currency and company_currency and currency != company_currency:
                try:
                    price = company_currency._convert(
                        price,
                        currency,
                        self.env.company,
                        fields.Date.today(),
                    )
                except Exception:
                    pass

        return math.ceil(float(price or 0.0))

    @api.model
    def get_sale_price_for_product(self, product_id=None, currency_code='USD', partner_id=None, quantity=1.0):
        """
        Endpoint RPC para que los wizards carguen precios de servicios desde backend.
        """
        if not product_id:
            return {
                'price_unit': 0.0,
                'currency_code': currency_code or 'USD',
            }

        product = self.env['product.product'].browse(int(product_id))
        if not product.exists():
            return {
                'price_unit': 0.0,
                'currency_code': currency_code or 'USD',
            }

        price_unit = self._compute_product_sale_price(
            product,
            currency_code=currency_code,
            partner_id=partner_id,
            quantity=quantity,
        )

        return {
            'product_id': product.id,
            'price_unit': price_unit,
            'currency_code': currency_code or 'USD',
        }

    @api.model
    def _normalize_services_for_hold(self, services=None, currency_code='USD', partner_id=None):
        """
        Normaliza los servicios del apartado. El precio capturado manualmente
        en el carrito SE RESPETA (mismo criterio que los materiales); el precio
        de lista del backend solo entra como default cuando no se envió precio.
        """
        normalized = []
        for service in (services or []):
            product_id = service.get('product_id')
            if not product_id:
                continue

            product = self.env['product.product'].browse(int(product_id))
            if not product.exists():
                continue

            qty = float(service.get('quantity') or 1.0)
            if qty <= 0:
                qty = 1.0

            try:
                price_unit = float(service.get('price_unit'))
            except (TypeError, ValueError):
                price_unit = 0.0

            if price_unit <= 0:
                price_unit = self._compute_product_sale_price(
                    product,
                    currency_code=currency_code,
                    partner_id=partner_id,
                    quantity=qty,
                )

            normalized.append({
                'product_id': product.id,
                'quantity': qty,
                'price_unit': price_unit,
            })

        return normalized

    @api.model
    def check_sales_permissions(self):
        """Verifica si el usuario tiene permisos de ventas"""
        return self.env.user.has_group('sales_team.group_sale_salesman') or \
            self.env.user.has_group('sales_team.group_sale_salesman_all_leads') or \
            self.env.user.has_group('sales_team.group_sale_manager')

    @api.model
    def check_inventory_permissions(self):
        """Verifica si el usuario tiene permisos de inventario"""
        return self.env.user.has_group('stock.group_stock_user')

    @api.model
    def get_internal_locations(self, search_term=''):
        """Obtener ubicaciones internas para traslados"""
        domain = [('usage', '=', 'internal')]

        if search_term:
            domain = ['&'] + domain + [
                '|', ('name', 'ilike', search_term),
                ('complete_name', 'ilike', search_term)
            ]

        locations = self.env['stock.location'].search(domain, limit=50)

        return [{
            'id': loc.id,
            'name': loc.name,
            'complete_name': loc.complete_name,
            'parent_name': loc.location_id.name if loc.location_id else ''
        } for loc in locations]

    @api.model
    def sync_cart_to_session(self, items):
        """Sincronizar carrito desde frontend a BD"""
        cart_model = self.env['shopping.cart']
        cart_model.clear_cart()

        for item in items:
            cart_model.add_to_cart(
                quant_id=item['id'],
                lot_id=item['lot_id'],
                product_id=item['product_id'],
                quantity=item['quantity'],
                location_name=item['location_name']
            )

        return {'success': True}

    # ============================================================
    # CANTIDADES SELECCIONADAS DESDE CARRITO / AUTORIZACIÓN
    # ============================================================

    def _resolve_selected_quantities(self, selected_lots=None, selected_quantities=None):
        """
        Resuelve la cantidad realmente seleccionada por quant.

        Prioridad:
        1. selected_quantities guardado en autorización.
        2. shopping.cart del vendedor actual.
        3. quantity completo del quant.

        Esto es crítico para formatos/piezas parciales, porque el hold no debe
        tomar siempre la cantidad completa del quant.
        """
        selected_lots = selected_lots or []
        clean_quant_ids = []

        for quant_id in selected_lots:
            try:
                clean_quant_ids.append(int(quant_id))
            except Exception:
                continue

        qty_by_quant = {}

        if isinstance(selected_quantities, dict):
            for key, value in selected_quantities.items():
                try:
                    qty_by_quant[int(key)] = float(value or 0.0)
                except Exception:
                    continue

        cart_owner_id = self.env.context.get('force_seller_id') or self.env.user.id

        if clean_quant_ids:
            cart_items = self.env['shopping.cart'].search([
                ('user_id', '=', cart_owner_id),
                ('quant_id', 'in', clean_quant_ids),
            ])

            for item in cart_items:
                qty_by_quant[item.quant_id.id] = item.quantity or 0.0

        for quant in self.browse(clean_quant_ids):
            if quant.id not in qty_by_quant:
                qty_by_quant[quant.id] = quant.quantity or 0.0

        return qty_by_quant

    # === GENERADOR ZPL ===

    @api.model
    def generate_zpl_labels(self, selected_lots, label_format):
        """
        Genera código ZPL para imprimir etiquetas de lotes.
        """
        if not selected_lots:
            return {'success': False, 'message': 'No hay lotes seleccionados'}

        quants = self.browse(selected_lots)
        zpl_code = ""

        # ── Canto/Lomo 17.5x1: 4 etiquetas por página, formato especial ──
        if label_format == '17.5x1':
            zpl_code = self._generate_canto_lomo_zpl(quants)
        else:
            for quant in quants:
                lot = quant.lot_id
                product_name = quant.product_id.name[:60] if quant.product_id.name else ''
                lot_name = lot.name or ''
                qty_str = ('%g' % (quant.quantity or 0)) + ' m2'

                zpl_code += "^XA^CI28"

                # DISEÑO (rotado 90°: media vertical, lectura horizontal):
                #   [SOM invertido] [LOTE grande]     ← banda superior
                #   PRODUCTO GIGANTE (hasta 2 líneas via ^FB)
                #   CÓDIGO DE BARRAS ENORME sin números (^BCR,...,N) + m²
                # Sin 'Lote:'/'Area:', sin dimensiones ni grosor.
                # 203 dpi → 1 cm = 80 dots. Canto/lomo NO se toca.
                # LAYOUT EN DOS MITADES (sin logo):
                #   ┌─────────────────────────────┐
                #   │   NOMBRE DEL MATERIAL (×2)  │  ← mitad superior
                #   ├─────────────────────────────┤
                #   │ CANTIDAD      ▐║█║║█║█║║▌  │  ← mitad inferior
                #   └─────────────────────────────┘
                if label_format == '10x5':
                    # GIRADA 90°: media horizontal — 10 cm de ancho (800) ×
                    # 5 cm de alto (400), texto en orientación NORMAL (^A0N).
                    # TODA la información va en la MITAD INFERIOR (y 200..392);
                    # la mitad superior queda limpia.
                    zpl_code += "^PW800^LL400"
                    # Marco solo de la mitad inferior
                    zpl_code += "^FO8,204^GB784,188,3^FS"
                    # Nombre del material: 2 líneas centradas
                    zpl_code += ("^FO10,214^A0N,36,36^FB780,2,4,C^FD"
                                 + product_name + "^FS")
                    # Cantidad a la izquierda
                    zpl_code += "^FO25,320^A0N,55,55^FD" + qty_str + "^FS"
                    # Código de barras al centro-derecha
                    zpl_code += ("^FO270,312^BY2,2,72^BCN,72,N,N,N^FD"
                                 + lot_name + "^FS")
                    # Logo SOM al extremo derecho de la franja
                    zpl_code += "^FO628,330" + SOM_LOGO_CANTO_ZPL + "^FS"

                elif label_format == '20x10':
                    # Media: 10 cm ancho (800) × 20 cm largo (1600)
                    # SIN LÍNEAS DE BORDE (marco y divisorias retirados).
                    zpl_code += "^PW800^LL1600"
                    # Nombre pegado al borde superior (rotado: x mayor = más
                    # arriba; la última línea cae en el origen).
                    zpl_code += ("^FO560,40^A0R,95,95^FB1520,2,8,C^FD"
                                 + product_name + "^FS")
                    # FILA DEL LOTE EN 2 COLUMNAS:
                    #   col 1 (mitad izquierda del largo): LOTE centrado
                    #   col 2 (mitad derecha): logo SOM
                    zpl_code += ("^FO415,40^A0R,120,120^FB740,1,0,C^FD"
                                 + lot_name + "^FS")
                    zpl_code += "^FO405,980" + SOM_LOGO_ZPL + "^FS"
                    zpl_code += "^FO130,70^A0R,125,125^FD" + qty_str + "^FS"
                    # Barras un poco más angostas para dar lugar al NÚMERO DE
                    # LOTE legible (se perdió en el rediseño 'sin números' del
                    # 2026-08-07 y en piso se necesita leerlo a ojo).
                    zpl_code += ("^FO95,620^BY5,2,295^BCR,295,N,N,N^FD"
                                 + lot_name + "^FS")
                    zpl_code += ("^FO25,620^A0R,60,60^FD"
                                 + lot_name + "^FS")

                zpl_code += "^XZ"

        return {
            'success': True,
            'zpl_data': zpl_code,
            'filename': f'etiquetas_{label_format}_{fields.Date.today()}.zpl'
        }

    def _generate_canto_lomo_zpl(self, quants):
        """
        Genera etiquetas formato 17.5x1 cm (canto/lomo).
        4 etiquetas por página ^XA..^XZ, dispuestas en 4 columnas verticales.
        Offset X entre columnas: 176 dots.
        """
        zpl = ""
        col_offset = 176

        for i in range(0, len(quants), 4):
            batch = quants[i:i + 4]
            zpl += "^XA\n^PW720\n^LL1500\n^CI28\n"

            for idx, quant in enumerate(batch):
                x = idx * col_offset
                lot = quant.lot_id
                product = quant.product_id

                lot_name = (lot.name or '').strip()

                if '-' in lot_name:
                    lot_prefix, lot_suffix = lot_name.rsplit('-', 1)
                else:
                    lot_prefix, lot_suffix = lot_name, ''

                product_name = (product.name or '').strip()
                if len(product_name) > 45:
                    if product_name[45] == ' ' or product_name[:45].endswith(' '):
                        product_name = product_name[:45].rstrip()
                    else:
                        product_name = product_name[:45] + '...'

                alto_raw = getattr(lot, 'x_alto', 0) or 0
                ancho_raw = getattr(lot, 'x_ancho', 0) or 0
                alto_m = alto_raw / 100.0 if alto_raw > 10 else alto_raw
                ancho_m = ancho_raw / 100.0 if ancho_raw > 10 else ancho_raw
                area = quant.quantity or 0
                # LARGO x ALTO (largo ≡ x_ancho en este inventario); antes
                # salía invertido como alto x largo.
                dim_line = f"{ancho_m:.2f} x {alto_m:.2f} = {area:.2f} M2"

                lote_origen = (
                    getattr(lot, 'x_lote_origen', None)
                    or getattr(lot, 'x_bloque', None)
                    or getattr(lot, 'x_origen', None)
                    or lot_name
                )
                if hasattr(lote_origen, 'name'):
                    lote_origen = lote_origen.name
                lote_origen = str(lote_origen or '').strip()

                # Logo SOM en lugar del texto '( SOM )', mismo tamaño de
                # banda (160 de ancho, ~50 de alto, sin rotar como ^A0N).
                zpl += f"^FO{26 + x},14" + SOM_LOGO_CANTO_ZPL + "^FS\n"
                zpl += f"^FO{18 + x},75^A0N,35,37^FB160,1,0,C^FD{lot_prefix}^FS\n"
                zpl += f"^FO{28 + x},130^A0N,78,78^FB160,1,0,C^FD{lot_suffix}^FS\n"
                zpl += f"^FO{133 + x},232^A0R,35,35^FD{product_name}^FS\n"
                zpl += f"^FO{88 + x},232^A0R,35,35^FD{dim_line}^FS\n"
                zpl += f"^FO{38 + x},232^A0R,35,35^FD{lote_origen}^FS\n"
                zpl += f"^FO{12 + x},1017^BY3,2,154^BCB,154,N,N,N^FD{lot_name}^FS\n"

            zpl += "^XZ\n"

        return zpl

    def _get_partner_delivery_address(self, partner):
        """Construir dirección de entrega del cliente"""
        if not partner:
            return ''

        address_parts = []

        if partner.street:
            address_parts.append(partner.street)
        if partner.street2:
            address_parts.append(partner.street2)

        city_parts = []
        if partner.city:
            city_parts.append(partner.city)
        if partner.state_id:
            city_parts.append(partner.state_id.name)
        if partner.zip:
            city_parts.append(f"C.P. {partner.zip}")

        if city_parts:
            address_parts.append(', '.join(city_parts))

        if partner.country_id:
            address_parts.append(partner.country_id.name)

        return '\n'.join(address_parts) if address_parts else ''

    @api.model
    def _som_assert_project_of_partner(self, partner_id, project_id):
        """Regla cliente→proyectos: el proyecto elegido debe ser del cliente
        seleccionado (o no tener cliente aún). Se valida en SERVIDOR para que
        ningún flujo del carrito (apartado, OV, autorización) la brinque."""
        if not partner_id or not project_id:
            return
        project = self.env['project.project'].browse(int(project_id)).exists()
        if not project or not project.partner_id:
            return
        partner = self.env['res.partner'].browse(int(partner_id)).exists()
        if partner and project.partner_id.commercial_partner_id != partner.commercial_partner_id:
            raise UserError(
                "El proyecto '%s' pertenece al cliente %s. "
                "Selecciona un proyecto del cliente elegido." % (
                    project.name, project.partner_id.display_name))

    @api.model
    def create_holds_from_cart(
        self,
        partner_id=None,
        project_id=None,
        architect_id=None,
        selected_lots=None,
        notes=None,
        currency_code='USD',
        product_prices=None,
        services=None,
        backorder_items=None,
        selected_quantities=None,
    ):
        """
        Crear múltiples apartados desde el carrito.

        Soporta:
        1. Lotes Físicos selected_lots -> crea stock.lot.hold.order y líneas con lot_ids.
        2. Material por Pedido backorder_items -> crea líneas sin lot_id.
        3. Servicios services -> crea líneas tipo servicio.

        Correcciones:
        - Respeta cantidades parciales seleccionadas desde carrito.
        - Calcula fecha de expiración desde stock.lot.hold.order.
        - Crea líneas con cantidad_m2, precio_unitario, subtotal y selector de precio.
        """
        selected_lots = selected_lots or []
        product_prices = product_prices or {}
        services = self._normalize_services_for_hold(
            services=services,
            currency_code=currency_code,
            partner_id=partner_id,
        )
        backorder_items = backorder_items or []

        has_lots = bool(selected_lots)
        has_services = bool(services)
        has_backorders = bool(backorder_items)

        if not partner_id or (not has_lots and not has_services and not has_backorders):
            return {
                'success': 0,
                'errors': 1,
                'failed': [{'error': 'Faltan parámetros requeridos o selección de items'}]
            }

        self._som_assert_project_of_partner(partner_id, project_id)

        selected_qty_by_quant = self._resolve_selected_quantities(
            selected_lots=selected_lots,
            selected_quantities=selected_quantities,
        )

        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            currency = self.env.company.currency_id

        # ================================================================
        # VERIFICAR AUTORIZACIÓN — LOTES FÍSICOS Y PEDIDOS SIN EXISTENCIA
        # ================================================================
        auth_price_map = {
            str(k): float(v or 0.0)
            for k, v in (product_prices or {}).items()
        }

        for item in backorder_items:
            try:
                product_id = int(item.get('product_id'))
                auth_price_map[str(product_id)] = float(item.get('price_unit') or 0.0)
            except Exception:
                continue

        if (has_lots or has_backorders) and not self.env.context.get('skip_authorization_check'):
            auth_check = self.env['product.template'].check_price_authorization_needed(
                auth_price_map,
                currency_code
            )

            if auth_check.get('needs_authorization'):
                product_groups = {}

                for quant_id in selected_lots:
                    quant = self.browse(int(quant_id))
                    if not quant.exists() or not quant.lot_id:
                        continue

                    pid = quant.product_id.id
                    selected_qty = selected_qty_by_quant.get(quant.id, quant.quantity or 0.0)

                    if pid not in product_groups:
                        product_groups[pid] = {
                            'name': quant.product_id.display_name,
                            'lots': [],
                            'total_quantity': 0.0,
                        }

                    product_groups[pid]['lots'].append({
                        'id': quant.id,
                        'lot_name': quant.lot_id.name,
                        'quantity': selected_qty,
                    })
                    product_groups[pid]['total_quantity'] += selected_qty

                for item in backorder_items:
                    try:
                        product_id = int(item.get('product_id'))
                    except Exception:
                        continue

                    product = self.env['product.product'].browse(product_id)
                    if not product.exists():
                        continue

                    if product_id not in product_groups:
                        product_groups[product_id] = {
                            'name': product.display_name,
                            'lots': [],
                            'total_quantity': 0.0,
                        }

                    product_groups[product_id]['total_quantity'] += float(item.get('quantity') or 0.0)

                result = self.create_price_authorization(
                    operation_type='hold',
                    partner_id=partner_id,
                    project_id=project_id,
                    selected_lots=selected_lots,
                    currency_code=currency_code,
                    product_prices=auth_price_map,
                    product_groups=product_groups,
                    notes=notes,
                    architect_id=architect_id,
                    selected_quantities=selected_qty_by_quant,
                    services=services,
                    backorder_items=backorder_items,
                )

                if result.get('success'):
                    return {
                        'success': False,
                        'needs_authorization': True,
                        'authorization_id': result['authorization_id'],
                        'authorization_name': result['authorization_name'],
                        'message': f'Solicitud {result["authorization_name"]} creada.',
                    }

        # ================================================================
        # NOTAS Y PRECIOS NORMALIZADOS
        # ================================================================
        full_notes = notes or ''
        normalized_prices = {}

        if product_prices and isinstance(product_prices, dict):
            normalized_prices = {str(k): float(v or 0.0) for k, v in product_prices.items()}

        fecha_orden = datetime.now()
        fecha_expiracion = self.env['stock.lot.hold.order']._get_default_fecha_expiracion(fecha_orden)

        partner = self.env['res.partner'].browse(partner_id)

        hold_order_vals = {
            'partner_id': partner_id,
            'user_id': self.env.context.get('force_seller_id', self.env.user.id),
            'project_id': project_id,
            'arquitecto_id': architect_id,
            'notas': full_notes,
            'company_id': self.env.company.id,
            'fecha_orden': fecha_orden,
            'fecha_expiracion': fecha_expiracion,
            'currency_id': currency.id,
            'delivery_address': self._get_partner_delivery_address(partner),
        }

        order = self.env['stock.lot.hold.order'].create(hold_order_vals)

        success_count = 0
        error_count = 0
        failed_lots = []

        line_model = self.env['stock.lot.hold.order.line']

        # ================================================================
        # 1. LOTES FÍSICOS — AGRUPAR POR PRODUCTO
        # ================================================================
        if has_lots:
            product_quants = {}

            for quant_id in selected_lots:
                try:
                    quant = self.browse(int(quant_id))

                    if not quant.exists() or not quant.lot_id:
                        continue

                    if hasattr(quant, 'x_tiene_hold') and quant.x_tiene_hold:
                        error_count += 1
                        failed_lots.append({
                            'lot_name': quant.lot_id.name,
                            'error': 'Ya tiene apartado',
                        })
                        continue

                    selected_qty = selected_qty_by_quant.get(quant.id, quant.quantity or 0.0)
                    pid = quant.product_id.id

                    if pid not in product_quants:
                        product_quants[pid] = {
                            'product_id': pid,
                            'items': [],
                            'lot_ids': [],
                        }

                    product_quants[pid]['items'].append({
                        'quant': quant,
                        'quantity': selected_qty,
                    })
                    product_quants[pid]['lot_ids'].append(quant.lot_id.id)

                except Exception as e:
                    error_count += 1
                    failed_lots.append({
                        'lot_name': f'Quant {quant_id}',
                        'error': str(e),
                    })

            for pid, group in product_quants.items():
                try:
                    precio_unitario = float(normalized_prices.get(str(pid), 0.0))
                    cantidad_m2 = sum(item['quantity'] for item in group['items'])
                    first_quant = group['items'][0]['quant']

                    # Desglose de parcialidades por lote (FORMATOS / PIEZAS).
                    # Para PLACAS no se guarda: siempre es el lote completo.
                    # Esto preserva la cantidad parcial exacta seleccionada en el
                    # carrito, igual que x_lot_breakdown_json en sale.order.line,
                    # para que el apartado no la interprete como el 100% del lote.
                    breakdown = {}
                    for item in group['items']:
                        lot = item['quant'].lot_id
                        if not lot:
                            continue
                        tipo = str(getattr(lot, 'x_tipo', '') or 'placa').lower()
                        if tipo not in ('formato', 'pieza'):
                            continue
                        key = str(lot.id)
                        breakdown[key] = breakdown.get(key, 0.0) + float(item['quantity'] or 0.0)

                    line_vals = {
                        'order_id': order.id,
                        'product_id': pid,
                        'lot_ids': [(6, 0, group['lot_ids'])],
                        'lot_id': group['lot_ids'][0],
                        'quant_id': first_quant.id,
                        'cantidad_m2': cantidad_m2,
                        'precio_unitario': precio_unitario,
                        'x_price_selector': line_model._selector_from_price(
                            pid,
                            currency_code,
                            precio_unitario,
                        ),
                    }
                    if breakdown and 'x_lot_breakdown_json' in line_model._fields:
                        line_vals['x_lot_breakdown_json'] = breakdown

                    line_model.with_context(skip_hold_line_quantity_sync=True).create(line_vals)

                    success_count += len(group['lot_ids'])

                except Exception as e:
                    error_count += len(group['lot_ids'])
                    failed_lots.append({
                        'lot_name': f'Producto {pid}',
                        'error': str(e),
                    })

        # ================================================================
        # 2. BACKORDERS — SIN LOTE, SOLO CANTIDAD FINANCIERA
        # ================================================================
        if has_backorders:
            for item in backorder_items:
                try:
                    product_id = int(item['product_id'])
                    price_unit = float(item['price_unit'] or 0.0)

                    line_model.create({
                        'order_id': order.id,
                        'product_id': product_id,
                        'lot_id': False,
                        'quant_id': False,
                        'cantidad_m2': float(item['quantity'] or 0.0),
                        'precio_unitario': price_unit,
                        'x_price_selector': line_model._selector_from_price(
                            product_id,
                            currency_code,
                            price_unit,
                        ),
                    })

                except Exception as e:
                    error_count += 1
                    failed_lots.append({
                        'lot_name': f"Pedido ID {item.get('product_id')}",
                        'error': str(e),
                    })

        # ================================================================
        # 3. SERVICIOS
        # ================================================================
        if has_services:
            for service in services:
                try:
                    line_model.create({
                        'order_id': order.id,
                        'product_id': int(service['product_id']),
                        'lot_id': False,
                        'quant_id': False,
                        'cantidad_m2': float(service['quantity'] or 0.0),
                        'precio_unitario': float(service['price_unit'] or 0.0),
                        'x_price_selector': 'custom',
                    })

                except Exception as e:
                    error_count += 1
                    failed_lots.append({
                        'lot_name': f"Servicio ID {service.get('product_id')}",
                        'error': str(e),
                    })

        has_content = success_count > 0 or has_backorders or has_services

        if has_content:
            try:
                order.with_context(
                    skip_authorization_check=True,
                    skip_hold_line_quantity_sync=True,
                ).action_confirm()

            except Exception as e:
                return {
                    'success': 0,
                    'errors': 1,
                    'failed': [{'error': f'Error confirmando: {str(e)}'}],
                }
        else:
            if order:
                order.unlink()

        return {
            'success': success_count,
            'errors': error_count,
            'failed': failed_lots,
            'order_id': order.id if order else None,
            'order_name': order.name if order else None,
        }

    @api.model
    def create_price_authorization(
        self,
        operation_type,
        partner_id,
        project_id,
        selected_lots,
        currency_code,
        product_prices,
        product_groups,
        notes=None,
        architect_id=None,
        selected_quantities=None,
        services=None,
        backorder_items=None,
    ):
        """Crea solicitud de autorización de precio"""
        self._som_assert_project_of_partner(partner_id, project_id)
        if isinstance(product_prices, dict):
            product_prices = {str(k): v for k, v in product_prices.items()}

        selected_quantities = selected_quantities or {}

        auth = self.env['price.authorization'].create({
            'seller_id': self.env.user.id,
            'operation_type': operation_type,
            'partner_id': partner_id,
            'project_id': project_id,
            'currency_code': currency_code,
            'notes': notes or '',
            'temp_data': {
                'selected_lots': selected_lots,
                'selected_quantities': {
                    str(k): float(v or 0.0)
                    for k, v in selected_quantities.items()
                },
                'product_prices': product_prices,
                'product_groups': product_groups,
                'architect_id': architect_id,
                'services': services or [],
                'backorder_items': backorder_items or [],
            },
        })

        Product = self.env['product.template']
        for product_id_key, group in product_groups.items():
            product_id = int(product_id_key)
            product = self.env['product.product'].browse(product_id)
            tmpl = product.product_tmpl_id

            requested_price = float(product_prices.get(str(product_id), 0.0))

            self.env['price.authorization.line'].create({
                'authorization_id': auth.id,
                'product_id': product_id,
                'quantity': group['total_quantity'],
                'lot_count': len(group['lots']),
                'requested_price': requested_price,
                'authorized_price': requested_price,
                'medium_price': Product._get_price_level_value(tmpl, 'medium', currency_code),
                'minimum_price': Product._get_price_level_value(tmpl, 'minimum', currency_code),
                'level_4_price': Product._get_price_level_value(tmpl, 'level_4', currency_code),
                'level_5_price': Product._get_price_level_value(tmpl, 'level_5', currency_code),
            })

        return {
            'success': True,
            'authorization_id': auth.id,
            'authorization_name': auth.name,
        }