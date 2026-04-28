# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockQuantSalePopup(models.Model):
    _inherit = "stock.quant"

    # -------------------------------------------------------------------------
    # Helpers de formato / normalización
    # -------------------------------------------------------------------------

    @api.model
    def _sale_popup_format_date(self, value):
        if not value:
            return ""

        try:
            if isinstance(value, str):
                return value

            if hasattr(value, "date"):
                return fields.Date.to_string(value.date())

            return str(value)
        except Exception:
            return ""

    @api.model
    def _sale_popup_trim_location(self, location_name):
        """
        Normaliza la ubicación para evitar rutas largas como:
            SOM/Existencias/A/Linea A-22

        Resultado:
            Existencias/A/Linea A-22

        Regla:
        - Si encuentra 'Existencias', conserva desde ahí hacia adelante.
        - Si no encuentra 'Existencias', intenta quitar el primer segmento.
        """
        if not location_name:
            return ""

        parts = [part.strip() for part in str(location_name).split("/") if part.strip()]

        if not parts:
            return ""

        lowered = [part.lower() for part in parts]

        for idx, part in enumerate(lowered):
            if part in ["existencias", "existencia"]:
                return "/".join(parts[idx:])

        if len(parts) > 1:
            return "/".join(parts[1:])

        return parts[0]

    @api.model
    def _sale_popup_get_first_value(self, record, field_names):
        if not record:
            return False

        for field_name in field_names:
            try:
                if field_name in record._fields:
                    value = record[field_name]
                    if value:
                        return value
            except Exception:
                continue

        return False

    @api.model
    def _sale_popup_get_currency_symbol(self, order):
        if order and order.currency_id:
            return order.currency_id.symbol or order.currency_id.name or "$"

        return "$"

    # -------------------------------------------------------------------------
    # Resolución de orden de venta relacionada
    # -------------------------------------------------------------------------

    @api.model
    def _sale_popup_find_sale_line_for_quant(self, quant):
        """
        Busca la línea de venta relacionada al quant.

        Prioridad:
        1. Líneas con x_selected_lots que contengan el quant.
        2. Líneas con lot_ids que contengan el stock.lot del quant.
        3. Movimientos de stock relacionados al lote y a una sale_line_id.
        """
        if not quant or not quant.exists():
            return self.env["sale.order.line"]

        SaleLine = self.env["sale.order.line"].sudo()

        line = SaleLine.search([
            ("x_selected_lots", "in", quant.id),
            ("order_id.state", "in", ["sale", "done"]),
        ], order="write_date desc, id desc", limit=1)

        if line:
            return line

        if quant.lot_id:
            line = SaleLine.search([
                ("lot_ids", "in", quant.lot_id.id),
                ("product_id", "=", quant.product_id.id),
                ("order_id.state", "in", ["sale", "done"]),
            ], order="write_date desc, id desc", limit=1)

            if line:
                return line

            move_line = self.env["stock.move.line"].sudo().search([
                ("lot_id", "=", quant.lot_id.id),
                ("product_id", "=", quant.product_id.id),
                ("move_id.sale_line_id", "!=", False),
                ("move_id.sale_line_id.order_id.state", "in", ["sale", "done"]),
            ], order="write_date desc, id desc", limit=1)

            if move_line and move_line.move_id.sale_line_id:
                return move_line.move_id.sale_line_id

        return self.env["sale.order.line"]

    @api.model
    def _sale_popup_compute_payment_info(self, order):
        """
        Calcula el estado de pago desde facturas publicadas.

        Nota:
        - Si no hay facturas publicadas, se considera sin pago.
        - El total mostrado siempre es el total de la orden.
        - El saldo pendiente se calcula contra el total de la orden.
        """
        if not order:
            return {
                "payment_state": "none",
                "payment_label": "Sin pago",
                "paid_percentage": 0.0,
                "amount_paid": 0.0,
                "amount_total": 0.0,
                "amount_residual": 0.0,
            }

        amount_total = order.amount_total or 0.0
        amount_paid = 0.0

        invoices = order.invoice_ids.filtered(
            lambda inv: inv.state == "posted"
            and inv.move_type in ["out_invoice", "out_refund"]
        )

        for invoice in invoices:
            sign = -1.0 if invoice.move_type == "out_refund" else 1.0
            paid_for_invoice = (invoice.amount_total or 0.0) - (invoice.amount_residual or 0.0)
            amount_paid += sign * paid_for_invoice

        if amount_paid < 0:
            amount_paid = 0.0

        if amount_paid > amount_total and amount_total > 0:
            amount_paid = amount_total

        amount_residual = amount_total - amount_paid
        if amount_residual < 0.01:
            amount_residual = 0.0

        paid_percentage = 0.0
        if amount_total > 0:
            paid_percentage = (amount_paid / amount_total) * 100.0

        if amount_paid <= 0.01:
            payment_state = "none"
            payment_label = "Sin pago"
        elif amount_residual <= 0.01:
            payment_state = "paid"
            payment_label = "Liquidado"
        else:
            payment_state = "partial"
            payment_label = "Pago parcial"

        return {
            "payment_state": payment_state,
            "payment_label": payment_label,
            "paid_percentage": paid_percentage,
            "amount_paid": amount_paid,
            "amount_total": amount_total,
            "amount_residual": amount_residual,
        }

    @api.model
    def _sale_popup_is_transit_location(self, location_name):
        text = (location_name or "").lower()
        return any(token in text for token in ["transit", "tránsito", "transito"])

    @api.model
    def _sale_popup_get_eta(self, quant, sale_line):
        """
        ETA solo se devuelve si el lote está en tránsito.

        Se intenta resolver desde:
        - Campos custom en quant.
        - Campos custom en lote.
        - Fecha programada del picking relacionado a la venta.
        """
        if not quant:
            return ""

        eta = self._sale_popup_get_first_value(
            quant,
            ["x_eta", "eta", "x_fecha_eta", "x_arrival_date", "arrival_date"],
        )

        if not eta and quant.lot_id:
            eta = self._sale_popup_get_first_value(
                quant.lot_id,
                ["x_eta", "eta", "x_fecha_eta", "x_arrival_date", "arrival_date"],
            )

        if not eta and sale_line:
            pickings = sale_line.move_ids.mapped("picking_id").filtered(
                lambda p: p.state not in ["done", "cancel"]
            )
            picking = pickings[:1]
            if picking:
                eta = self._sale_popup_get_first_value(
                    picking,
                    ["scheduled_date", "date_deadline", "x_eta", "eta"],
                )

        return self._sale_popup_format_date(eta)

    # -------------------------------------------------------------------------
    # Método público para OWL
    # -------------------------------------------------------------------------

    @api.model
    def get_sale_order_popup_info(self, quant_id):
        """
        Devuelve la información consolidada para el popup de SO relacionada.

        Evita redundancia:
        - Material: producto, lote, cantidad, ubicación, ETA solo en tránsito.
        - Orden: orden, cliente, vendedor, botón.
        - Pago: estado, %, pagado, total, saldo.
        """
        quant = self.sudo().browse(int(quant_id or 0))

        if not quant.exists():
            return {
                "success": False,
                "message": "No se encontró el lote/material seleccionado.",
            }

        sale_line = self._sale_popup_find_sale_line_for_quant(quant)
        order = sale_line.order_id if sale_line else self.env["sale.order"]

        full_location = quant.location_id.complete_name or quant.location_id.display_name or ""
        short_location = self._sale_popup_trim_location(full_location)

        is_transit = self._sale_popup_is_transit_location(full_location)
        eta = self._sale_popup_get_eta(quant, sale_line) if is_transit else ""

        payment_info = self._sale_popup_compute_payment_info(order)
        currency_symbol = self._sale_popup_get_currency_symbol(order)

        product_name = quant.product_id.display_name or ""
        lot_name = quant.lot_id.name or ""

        return {
            "success": True,

            # Material
            "quant_id": quant.id,
            "lot_id": quant.lot_id.id if quant.lot_id else False,
            "lot_name": lot_name,
            "product_id": quant.product_id.id,
            "product_name": product_name,
            "quantity": quant.quantity or 0.0,
            "uom": quant.product_uom_id.name if quant.product_uom_id else "m²",
            "location_name": short_location,
            "location_full_name": full_location,
            "is_transit": is_transit,
            "eta": eta,

            # Orden comercial
            "sale_order_id": order.id if order else False,
            "sale_order_name": order.name if order else "",
            "partner_name": order.partner_id.display_name if order and order.partner_id else "",
            "seller_name": order.user_id.name if order and order.user_id else "",

            # Pago
            "currency_symbol": currency_symbol,
            **payment_info,
        }