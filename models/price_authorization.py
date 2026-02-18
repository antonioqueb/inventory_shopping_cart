# ./models/price_authorization.py
# -*- coding: utf-8 -*-
import math
from odoo import models, fields, api
from odoo.exceptions import UserError

class PriceAuthorization(models.Model):
    _name = 'price.authorization'
    _description = 'Autorización de Precios Mínimos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    
    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True, default='Nuevo')
    seller_id = fields.Many2one('res.users', string='Vendedor', required=True, readonly=True)
    authorizer_id = fields.Many2one('res.users', string='Autorizado por')
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('approved', 'Aprobado'),
        ('rejected', 'Rechazado'),
        ('expired', 'Expirado')
    ], string='Estado', default='pending', required=True, tracking=True)
    
    operation_type = fields.Selection([
        ('hold', 'Apartado'),
        ('sale', 'Venta')
    ], string='Tipo de Operación', required=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', tracking=True)
    project_id = fields.Many2one('project.project', string='Proyecto', tracking=True)
    currency_code = fields.Selection([('USD', 'USD'), ('MXN', 'MXN')], string='Divisa', required=True)
    
    line_ids = fields.One2many('price.authorization.line', 'authorization_id', string='Productos')
    
    notes = fields.Text(string='Notas del Vendedor')
    authorization_notes = fields.Text(string='Notas del Autorizador')
    
    create_date = fields.Datetime(string='Fecha Solicitud', readonly=True)
    authorization_date = fields.Datetime(string='Fecha Autorización', readonly=True, tracking=True)
    
    temp_data = fields.Json(string='Datos Temporales')
    sale_order_id = fields.Many2one('sale.order', string='Orden de Venta Generada', readonly=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = self.env['ir.sequence'].next_by_code('price.authorization') or 'Nuevo'
        
        records = super().create(vals_list)
        
        for record in records:
            record._notify_authorizers()
        
        return records
    
    def _notify_authorizers(self):
        """Notifica a todos los usuarios autorizadores sobre la nueva solicitud"""
        self.ensure_one()
        
        authorizer_group = self.env.ref('inventory_shopping_cart.group_price_authorizer')
        authorizers = authorizer_group.user_ids.filtered(lambda u: u.id != self.seller_id.id)
        
        if not authorizers:
            return
        
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([('name', '=', 'To Do')], limit=1)
        
        for authorizer in authorizers:
            self.activity_schedule(
                activity_type_id=activity_type.id,
                summary=f'Autorización {self.name}',
                note=f"""
                    <p>Se requiere su autorización para:</p>
                    <ul>
                        <li><strong>Vendedor:</strong> {self.seller_id.name}</li>
                        <li><strong>Cliente:</strong> {self.partner_id.name}</li>
                        <li><strong>Operación:</strong> {'Venta' if self.operation_type == 'sale' else 'Apartado'}</li>
                        <li><strong>Productos:</strong> {len(self.line_ids)} productos</li>
                    </ul>
                """,
                user_id=authorizer.id
            )
        
    def _notify_seller(self, approved=True):
        """Notifica al vendedor sobre la decisión"""
        self.ensure_one()
        
        if approved:
            status = "APROBADA"
            activity_summary = f'Autorización Aprobada - {self.name}'
            message_text = f"<p>Su solicitud {self.name} ha sido <strong>aprobada</strong> por {self.authorizer_id.name}.</p>"
            
            if self.operation_type == 'sale' and self.sale_order_id:
                message_text += f"<p>Orden de venta generada: <a href='/web#id={self.sale_order_id.id}&model=sale.order&view_type=form'>{self.sale_order_id.name}</a></p>"
            elif self.operation_type == 'hold':
                message_text += "<p>Los apartados han sido creados automáticamente.</p>"
        else:
            status = "RECHAZADA"
            activity_summary = f'Autorización Rechazada - {self.name}'
            message_text = f"<p>Su solicitud {self.name} ha sido <strong>rechazada</strong> por {self.authorizer_id.name}.</p>"
        
        if self.authorization_notes:
            message_text += f"<p><strong>Comentarios:</strong><br/>{self.authorization_notes}</p>"
        
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([('name', '=', 'To Do')], limit=1)
        
        self.activity_schedule(
            activity_type_id=activity_type.id,
            summary=activity_summary,
            note=message_text,
            user_id=self.seller_id.id
        )
    
    def action_approve(self):
        self.ensure_one()
        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("No tiene permisos para autorizar precios")
        
        self.activity_ids.filtered(lambda a: a.user_id == self.env.user).action_done()
        
        self.write({
            'state': 'approved',
            'authorizer_id': self.env.user.id,
            'authorization_date': fields.Datetime.now()
        })
        
        self._process_approved_authorization()
        self._notify_seller(approved=True)
        
    def action_reject(self):
        self.ensure_one()
        if not self.env.user.has_group('inventory_shopping_cart.group_price_authorizer'):
            raise UserError("No tiene permisos para rechazar precios")
        
        self.activity_ids.filtered(lambda a: a.user_id == self.env.user).action_done()
        
        self.write({
            'state': 'rejected',
            'authorizer_id': self.env.user.id,
            'authorization_date': fields.Datetime.now()
        })
        
        self._notify_seller(approved=False)
    
    def _process_approved_authorization(self):
        """
        Procesa la autorización aprobada.
        FIX: Siempre usa authorized_price (precio definido por el autorizador).
        FIX: Si viene de una orden manual existente, actualiza sus precios en vez de crear nueva.
        """
        self.ensure_one()
        
        if not self.temp_data:
            raise UserError("No hay datos temporales para procesar")
        
        temp_data = self.temp_data
        
        pricelist = self.env['product.pricelist'].search([('name', '=', self.currency_code)], limit=1)
        if not pricelist:
            raise UserError(f"No se encontró lista de precios para {self.currency_code}")
        
        if self.operation_type == 'sale':
            source = temp_data.get('source', '')
            existing_order_id = temp_data.get('sale_order_id') or (self.sale_order_id.id if self.sale_order_id else False)
            
            if source == 'manual_order' and existing_order_id:
                self._update_and_confirm_existing_order(existing_order_id)
            else:
                self._create_sale_order_from_authorization(pricelist, temp_data)
        elif self.operation_type == 'hold':
            self._create_holds_from_authorization(temp_data)

    def _update_and_confirm_existing_order(self, order_id):
        """
        FIX: Cuando la autorización viene de una orden manual existente,
        actualiza los precios con los AUTORIZADOS (redondeados hacia arriba) y confirma.
        """
        order = self.env['sale.order'].browse(order_id)
        if not order.exists():
            raise UserError(f"La orden de venta ID {order_id} ya no existe.")
        
        if order.state not in ['draft', 'sent']:
            raise UserError(f"La orden {order.name} ya no está en estado borrador.")
        
        for line in self.line_ids:
            order_lines = order.order_line.filtered(
                lambda l: l.product_id.id == line.product_id.id and not l.display_type
            )
            for ol in order_lines:
                ol.write({
                    'price_unit': math.ceil(line.authorized_price),
                    'x_price_selector': 'custom',
                })
        
        order.x_price_authorization_id = self.id
        order.with_context(skip_auth_check=True).action_confirm()
        self.write({'sale_order_id': order.id})
    
    def _create_sale_order_from_authorization(self, pricelist, temp_data):
        """
        Crea orden de venta desde autorización aprobada (flujo carrito).
        FIX: Usa authorized_price redondeado hacia arriba.
        """
        product_prices = {}
        for line in self.line_ids:
            product_prices[str(line.product_id.id)] = math.ceil(line.authorized_price)
        
        products = []
        product_groups = temp_data.get('product_groups', {})
        
        for product_id_str, group in product_groups.items():
            products.append({
                'product_id': int(product_id_str),
                'quantity': group['total_quantity'],
                'price_unit': float(product_prices.get(product_id_str, 0)),
                'selected_lots': [lot['id'] for lot in group['lots']]
            })
        
        services = temp_data.get('services', [])
        
        notes = self.notes or ''
        if self.project_id:
            notes += f'\n\n=== INFORMACIÓN DEL PROYECTO ===\n'
            notes += f'Proyecto: {self.project_id.name}\n'
        
        architect_id = temp_data.get('architect_id')
        if architect_id:
            architect = self.env['res.partner'].browse(architect_id)
            if architect.exists():
                notes += f'Arquitecto: {architect.name}\n'
        
        notes += f'\n\n=== AUTORIZACIÓN DE PRECIO ===\n'
        notes += f'Autorización: {self.name}\n'
        notes += f'Autorizado por: {self.authorizer_id.name}\n'
        notes += f'Fecha: {self.authorization_date}\n'
        
        apply_tax = temp_data.get('apply_tax', True)
        if not apply_tax:
            notes += '\n\n⚠️ NOTA IMPORTANTE: El IVA se agregará posteriormente.'
        
        company_id = self.env.context.get('company_id') or self.env.company.id
        
        for product in products:
            for quant_id in product['selected_lots']:
                quant = self.env['stock.quant'].browse(quant_id)
                if quant.x_tiene_hold:
                    hold_partner = quant.x_hold_activo_id.partner_id
                    if hold_partner.id != self.partner_id.id:
                        raise UserError(f"El lote {quant.lot_id.name} está apartado para {hold_partner.name}")
        
        sale_order = self.env['sale.order'].with_company(company_id).sudo().create({
            'partner_id': self.partner_id.id,
            'user_id': self.seller_id.id,
            'note': notes,
            'pricelist_id': pricelist.id,
            'company_id': company_id,
            'x_price_authorization_id': self.id,
        })
        
        for product in products:
            product_rec = self.env['product.product'].browse(product['product_id'])
            
            if apply_tax and product_rec.taxes_id:
                tax_ids = [(6, 0, product_rec.taxes_id.ids)]
            else:
                tax_ids = [(5, 0, 0)]
            
            self.env['sale.order.line'].with_company(company_id).sudo().create({
                'order_id': sale_order.id,
                'product_id': product['product_id'],
                'product_uom_qty': product['quantity'],
                'price_unit': product['price_unit'],
                'tax_ids': tax_ids,
                'x_selected_lots': [(6, 0, product['selected_lots'])],
                'x_price_selector': 'custom',
                'company_id': company_id,
            })
        
        if services:
            for service in services:
                service_product = self.env['product.product'].browse(service['product_id'])
                
                if apply_tax and service_product.taxes_id:
                    tax_ids = [(6, 0, service_product.taxes_id.ids)]
                else:
                    tax_ids = [(5, 0, 0)]
                
                self.env['sale.order.line'].with_company(company_id).sudo().create({
                    'order_id': sale_order.id,
                    'product_id': service['product_id'],
                    'product_uom_qty': service['quantity'],
                    'price_unit': math.ceil(service['price_unit']),
                    'tax_ids': tax_ids,
                    'company_id': company_id,
                })
        
        sale_order.with_company(company_id).with_context(skip_auth_check=True).sudo().action_confirm()
        
        for line in sale_order.order_line:
            if line.x_selected_lots:
                picking = line.move_ids.mapped('picking_id')
                if picking:
                    self.env['sale.order'].sudo()._assign_specific_lots(picking, line.product_id, line.x_selected_lots)
        
        self.write({'sale_order_id': sale_order.id})
    
    def _create_holds_from_authorization(self, temp_data):
        """
        Crea apartados desde autorización aprobada.
        FIX: Usa authorized_price redondeado hacia arriba.
        """
        product_prices = {}
        for line in self.line_ids:
            product_prices[str(line.product_id.id)] = math.ceil(line.authorized_price)
        
        selected_lots = temp_data.get('selected_lots', [])
        architect_id = temp_data.get('architect_id')
        
        full_notes = self.notes or ''
        full_notes += f'\n\n=== AUTORIZACIÓN DE PRECIO ===\n'
        full_notes += f'Autorización: {self.name}\n'
        full_notes += f'Autorizado por: {self.authorizer_id.name}\n'
        full_notes += f'Fecha: {self.authorization_date}\n'
        
        result = self.env['stock.quant'].with_context(
            skip_authorization_check=True,
            force_seller_id=self.seller_id.id
        ).create_holds_from_cart(
            partner_id=self.partner_id.id,
            project_id=self.project_id.id if self.project_id else None,
            architect_id=architect_id,
            selected_lots=selected_lots,
            notes=full_notes,
            currency_code=self.currency_code,
            product_prices=product_prices
        )
        
        if result.get('success', 0) == 0 and result.get('errors', 0) > 0:
            error_msg = "Errores al crear apartados:\n"
            for failed in result.get('failed', []):
                error_msg += f"• {failed.get('lot_name', 'Lote')}: {failed.get('error', 'Error desconocido')}\n"
            raise UserError(error_msg)

class PriceAuthorizationLine(models.Model):
    _name = 'price.authorization.line'
    _description = 'Línea de Autorización de Precio'
    
    authorization_id = fields.Many2one('price.authorization', string='Autorización', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    quantity = fields.Float(string='Cantidad m²', required=True)
    lot_count = fields.Integer(string='# Lotes', required=True)
    
    requested_price = fields.Float(string='Precio Solicitado', required=True, digits='Product Price')
    medium_price = fields.Float(string='Precio Medio', readonly=True, digits='Product Price')
    minimum_price = fields.Float(string='Precio Mínimo', readonly=True, digits='Product Price')
    
    authorized_price = fields.Float(
        string='Precio Autorizado', 
        required=True, 
        digits='Product Price',
        help='Precio final autorizado. Puede ser diferente al solicitado.'
    )
    
    price_level = fields.Selection([
        ('below_minimum', 'Debajo del Mínimo'),
        ('minimum', 'Precio Mínimo'),
        ('below_medium', 'Entre Mínimo y Medio')
    ], string='Nivel de Precio', compute='_compute_price_level', store=True)
    
    @api.depends('requested_price', 'minimum_price', 'medium_price')
    def _compute_price_level(self):
        for line in self:
            if line.requested_price < line.minimum_price:
                line.price_level = 'below_minimum'
            elif line.requested_price == line.minimum_price:
                line.price_level = 'minimum'
            else:
                line.price_level = 'below_medium'
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'requested_price' in vals:
                vals['requested_price'] = math.ceil(vals['requested_price'])
            if 'authorized_price' not in vals and 'requested_price' in vals:
                vals['authorized_price'] = vals['requested_price']
            elif 'authorized_price' in vals:
                vals['authorized_price'] = math.ceil(vals['authorized_price'])
            if 'medium_price' in vals:
                vals['medium_price'] = math.ceil(vals['medium_price'])
            if 'minimum_price' in vals:
                vals['minimum_price'] = math.ceil(vals['minimum_price'])
        return super().create(vals_list)
    
    def write(self, vals):
        if 'requested_price' in vals:
            vals['requested_price'] = math.ceil(vals['requested_price'])
        if 'authorized_price' in vals:
            vals['authorized_price'] = math.ceil(vals['authorized_price'])
        if 'medium_price' in vals:
            vals['medium_price'] = math.ceil(vals['medium_price'])
        if 'minimum_price' in vals:
            vals['minimum_price'] = math.ceil(vals['minimum_price'])
        return super().write(vals)