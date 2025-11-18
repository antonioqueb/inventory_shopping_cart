# ./models/price_authorization.py
# -*- coding: utf-8 -*-
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
        
        products_summary = []
        for line in self.line_ids:
            products_summary.append(
                f"• {line.product_id.display_name}: {line.quantity:.2f} m² "
                f"(Precio solicitado: {line.requested_price:.2f} {self.currency_code})"
            )
        
        message_body = f"""
        <p><strong>Nueva solicitud de autorización de precio</strong></p>
        <ul>
            <li><strong>Solicitado por:</strong> {self.seller_id.name}</li>
            <li><strong>Cliente:</strong> {self.partner_id.name}</li>
            <li><strong>Tipo:</strong> {'Venta' if self.operation_type == 'sale' else 'Apartado'}</li>
            <li><strong>Divisa:</strong> {self.currency_code}</li>
        </ul>
        <p><strong>Productos:</strong></p>
        <ul>
            {''.join(f'<li>{summary}</li>' for summary in products_summary)}
        </ul>
        """
        
        if self.notes:
            message_body += f"<p><strong>Notas del vendedor:</strong><br/>{self.notes}</p>"
        
        # ✅ NOTIFICACIÓN AUTOMÁTICA EN CHATTER + INBOX
        # Al usar partner_ids, Odoo crea automáticamente:
        # 1. El mensaje en el chatter
        # 2. Notificaciones en el inbox para cada partner
        # 3. El subtype 'mail.mt_comment' hace que sea visible
        self.message_post(
            body=message_body,
            subject=f"Solicitud de Autorización {self.name}",
            partner_ids=authorizers.mapped('partner_id').ids,
            message_type='comment',  # ✅ Cambiado de 'notification' a 'comment'
            subtype_xmlid='mail.mt_comment'
        )
        
        # Crear actividad para cada autorizador
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([('name', '=', 'To Do')], limit=1)
        
        for authorizer in authorizers:
            self.activity_schedule(
                activity_type_id=activity_type.id,
                summary=f'Autorizar precio - {self.name}',
                note=f"""
                    <p>Se requiere su autorización para:</p>
                    <ul>
                        <li><strong>Vendedor:</strong> {self.seller_id.name}</li>
                        <li><strong>Cliente:</strong> {self.partner_id.name}</li>
                        <li><strong>Operación:</strong> {'Venta' if self.operation_type == 'sale' else 'Apartado'}</li>
                        <li><strong>Productos:</strong> {len(self.line_ids)} productos</li>
                    </ul>
                    <p>Revise los precios solicitados y apruebe o rechace la solicitud.</p>
                """,
                user_id=authorizer.id
            )
        
        # Notificación adicional via correo
        template = self.env.ref('inventory_shopping_cart.email_template_price_authorization_request', raise_if_not_found=False)
        if template:
            for authorizer in authorizers:
                template.send_mail(
                    self.id,
                    force_send=True,
                    email_values={'email_to': authorizer.email}
                )
        
    def _notify_seller(self, approved=True):
        """Notifica al vendedor sobre la decisión"""
        self.ensure_one()
        
        if approved:
            status = "✅ APROBADA"
            message_text = f"Su solicitud de autorización {self.name} ha sido aprobada por {self.authorizer_id.name}."
            
            if self.operation_type == 'sale' and self.sale_order_id:
                message_text += f"<br/>Se ha generado la orden de venta: <a href='/web#id={self.sale_order_id.id}&model=sale.order&view_type=form'>{self.sale_order_id.name}</a>"
            elif self.operation_type == 'hold':
                message_text += "<br/>Los apartados han sido creados automáticamente."
        else:
            status = "❌ RECHAZADA"
            message_text = f"Su solicitud de autorización {self.name} ha sido rechazada por {self.authorizer_id.name}."
        
        if self.authorization_notes:
            message_text += f"<br/><br/><strong>Comentarios del autorizador:</strong><br/>{self.authorization_notes}"
        
        # ✅ NOTIFICACIÓN AUTOMÁTICA EN CHATTER + INBOX
        self.message_post(
            body=message_text,
            subject=f"Solicitud {status} - {self.name}",
            partner_ids=[self.seller_id.partner_id.id],
            message_type='comment',  # ✅ Cambiado de 'notification' a 'comment'
            subtype_xmlid='mail.mt_comment'
        )
        
        # Crear actividad para el vendedor
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([('name', '=', 'To Do')], limit=1)
        
        activity_note = message_text
        if approved and self.operation_type == 'sale' and self.sale_order_id:
            activity_note += "<br/><br/>Por favor, continúe con el proceso de la orden de venta."
        
        self.activity_schedule(
            activity_type_id=activity_type.id,
            summary=f'Autorización {status} - {self.name}',
            note=activity_note,
            user_id=self.seller_id.id
        )
        
        # Notificación por correo
        template_xmlid = 'inventory_shopping_cart.email_template_price_authorization_approved' if approved else 'inventory_shopping_cart.email_template_price_authorization_rejected'
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
    
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
        
        self.message_post(
            body=f"Solicitud aprobada por {self.env.user.name}",
            subject="Autorización Aprobada"
        )
        
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
        
        self.message_post(
            body=f"Solicitud rechazada por {self.env.user.name}",
            subject="Autorización Rechazada"
        )
        
        self._notify_seller(approved=False)
    
    def _process_approved_authorization(self):
        """Procesa la autorización aprobada"""
        self.ensure_one()
        
        if not self.temp_data:
            raise UserError("No hay datos temporales para procesar")
        
        temp_data = self.temp_data
        
        pricelist = self.env['product.pricelist'].search([('name', '=', self.currency_code)], limit=1)
        if not pricelist:
            raise UserError(f"No se encontró lista de precios para {self.currency_code}")
        
        if self.operation_type == 'sale':
            self._create_sale_order_from_authorization(pricelist, temp_data)
        elif self.operation_type == 'hold':
            self._create_holds_from_authorization(temp_data)
    
    def _create_sale_order_from_authorization(self, pricelist, temp_data):
        """Crea orden de venta desde autorización aprobada"""
        
        product_prices = {}
        for line in self.line_ids:
            product_prices[str(line.product_id.id)] = line.authorized_price
        
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
                    'price_unit': service['price_unit'],
                    'tax_ids': tax_ids,
                    'company_id': company_id,
                })
        
        sale_order.with_company(company_id).sudo().action_confirm()
        
        for line in sale_order.order_line:
            if line.x_selected_lots:
                picking = line.move_ids.mapped('picking_id')
                if picking:
                    self.env['sale.order'].sudo()._assign_specific_lots(picking, line.product_id, line.x_selected_lots)
        
        self.write({'sale_order_id': sale_order.id})
        
        self.message_post(
            body=f"Orden de venta {sale_order.name} creada automáticamente",
            subject="Orden Creada"
        )
    
    def _create_holds_from_authorization(self, temp_data):
        """Crea apartados desde autorización aprobada"""
        
        product_prices = {}
        for line in self.line_ids:
            product_prices[str(line.product_id.id)] = line.authorized_price
        
        selected_lots = temp_data.get('selected_lots', [])
        architect_id = temp_data.get('architect_id')
        
        result = self.env['stock.quant'].create_holds_from_cart(
            partner_id=self.partner_id.id,
            project_id=self.project_id.id if self.project_id else None,
            architect_id=architect_id,
            selected_lots=selected_lots,
            notes=self.notes,
            currency_code=self.currency_code,
            product_prices=product_prices
        )
        
        if result['success'] > 0:
            self.message_post(
                body=f"{result['success']} apartados creados automáticamente",
                subject="Apartados Creados"
            )
        
        if result['errors'] > 0:
            error_msg = f"{result['errors']} apartados fallaron:\n"
            for failed in result['failed']:
                error_msg += f"\n• {failed['lot_name']}: {failed['error']}"
            self.message_post(
                body=error_msg,
                subject="Errores en Apartados"
            )

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
            if 'authorized_price' not in vals and 'requested_price' in vals:
                vals['authorized_price'] = vals['requested_price']
        return super().create(vals_list)