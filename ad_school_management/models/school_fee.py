from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolFeeStructure(models.Model):
    _name = 'school.fee.structure'
    _description = 'Fee Structure'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Structure Name', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    line_ids = fields.One2many('school.fee.structure.line', 'fee_structure_id', string='Fee Components')
    installment_ids = fields.One2many('school.fee.installment', 'fee_structure_id', string='Installments')
    total_amount = fields.Float(string='Total Amount', compute='_compute_total_amount', store=True)

    _code_uniq = models.Constraint(
        'unique(code)', 'The fee structure code must be unique!'
    )

    @api.depends('line_ids.amount')
    def _compute_total_amount(self):
        for struct in self:
            struct.total_amount = sum(struct.line_ids.mapped('amount'))

class SchoolFeeStructureLine(models.Model):
    _name = 'school.fee.structure.line'
    _description = 'Fee Structure Line'

    fee_structure_id = fields.Many2one('school.fee.structure', string='Fee Structure', required=True, ondelete='cascade')
    name = fields.Char(string='Component Name', required=True)
    amount = fields.Float(string='Amount', required=True)
    product_id = fields.Many2one('product.product', string='Product Reference', required=True)

    @api.constrains('amount')
    def _check_amount(self):
        for line in self:
            if line.amount <= 0:
                raise ValidationError(_("Component amount must be greater than zero."))

class SchoolFeeInstallment(models.Model):
    _name = 'school.fee.installment'
    _description = 'Fee Installment'
    _order = 'due_date'

    fee_structure_id = fields.Many2one('school.fee.structure', string='Fee Structure', required=True, ondelete='cascade')
    name = fields.Char(string='Installment Name', required=True)
    due_date = fields.Date(string='Due Date', required=True)
    amount_percentage = fields.Float(string='Percentage (%)', default=100.0, required=True)

    @api.constrains('amount_percentage')
    def _check_percentage(self):
        for inst in self:
            if inst.amount_percentage <= 0 or inst.amount_percentage > 100:
                raise ValidationError(_("Installment percentage must be between 1 and 100."))

class SchoolStudentFee(models.Model):
    _name = 'school.student.fee'
    _description = 'Student Fee'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Fee Reference', required=True, readonly=True, default='/', copy=False)
    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True)
    structure_id = fields.Many2one('school.fee.structure', string='Fee Structure', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', related='structure_id.academic_year_id', store=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    amount = fields.Float(string='Structure Total', compute='_compute_amount', store=True)
    discount = fields.Float(string='Discount (Flat)', default=0.0, tracking=True)
    scholarship = fields.Float(string='Scholarship (%)', default=0.0, tracking=True)
    net_amount = fields.Float(string='Net Amount', compute='_compute_net_amount', store=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled')
    ], string='Status', compute='_compute_state_from_invoice', store=True, default='draft', tracking=True)
    
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)
    invoice_state = fields.Selection(related='invoice_id.payment_state', string='Invoice Payment State', store=True)
    installment_line_ids = fields.One2many('school.student.fee.installment', 'student_fee_id', string='Installments', copy=True)

    _student_struct_uniq = models.Constraint(
        'unique(student_id, structure_id)', 'This fee structure is already assigned to this student!'
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.student.fee.seq') or '/'
            if not vals.get('company_id'):
                student = self.env['school.student'].browse(vals.get('student_id'))
                vals['company_id'] = student.company_id.id or self.env.company.id
        records = super(SchoolStudentFee, self).create(vals_list)
        for record in records:
            record._generate_installments()
        return records

    def write(self, vals):
        if 'student_id' in vals and not vals.get('company_id'):
            student = self.env['school.student'].browse(vals['student_id'])
            vals['company_id'] = student.company_id.id or self.env.company.id
        res = super(SchoolStudentFee, self).write(vals)
        if 'structure_id' in vals:
            for record in self:
                record.installment_line_ids.filtered(lambda i: not i.invoice_id).unlink()
                record._generate_installments()
        return res

    def _generate_installments(self):
        for rec in self:
            if not rec.structure_id:
                continue
            if rec.installment_line_ids:
                continue
            if rec.structure_id.installment_ids:
                for inst in rec.structure_id.installment_ids:
                    self.env['school.student.fee.installment'].create({
                        'student_fee_id': rec.id,
                        'name': inst.name,
                        'due_date': inst.due_date,
                        'amount_percentage': inst.amount_percentage,
                    })
            else:
                self.env['school.student.fee.installment'].create({
                    'student_fee_id': rec.id,
                    'name': _("Full Fee Payment"),
                    'due_date': fields.Date.context_today(rec),
                    'amount_percentage': 100.0,
                })

    @api.depends('structure_id')
    def _compute_amount(self):
        for fee in self:
            fee.amount = fee.structure_id.total_amount if fee.structure_id else 0.0

    @api.depends('amount', 'discount', 'scholarship')
    def _compute_net_amount(self):
        for fee in self:
            net = fee.amount - fee.discount
            if fee.scholarship:
                net = net * (1.0 - (fee.scholarship / 100.0))
            fee.net_amount = max(net, 0.0)

    @api.depends('installment_line_ids.state')
    def _compute_state_from_invoice(self):
        for rec in self:
            if rec.installment_line_ids:
                states = rec.installment_line_ids.mapped('state')
                if all(s == 'draft' for s in states):
                    rec.state = 'draft'
                elif all(s == 'paid' for s in states):
                    rec.state = 'paid'
                elif all(s == 'cancelled' for s in states):
                    rec.state = 'cancelled'
                else:
                    rec.state = 'invoiced'
            else:
                rec.state = 'draft'

    def action_create_invoice(self):
        for rec in self:
            uninvoiced = rec.installment_line_ids.filtered(lambda i: not i.invoice_id)
            if not uninvoiced:
                raise ValidationError(_("No draft installments available to invoice."))
            for inst in uninvoiced:
                inst.action_create_invoice()

    def action_view_invoice(self):
        self.ensure_one()
        invoices = self.installment_line_ids.mapped('invoice_id')
        if not invoices:
            return
        if len(invoices) == 1:
            return {
                'name': _("Invoice"),
                'view_mode': 'form',
                'res_model': 'account.move',
                'res_id': invoices[0].id,
                'type': 'ir.actions.act_window',
                'context': {'create': False},
            }
        return {
            'name': _("Invoices"),
            'view_mode': 'list,form',
            'res_model': 'account.move',
            'domain': [('id', 'in', invoices.ids)],
            'type': 'ir.actions.act_window',
            'context': {'create': False},
        }

class SchoolStudentFeeInstallment(models.Model):
    _name = 'school.student.fee.installment'
    _description = 'Student Fee Installment'
    _order = 'due_date'

    student_fee_id = fields.Many2one('school.student.fee', string='Student Fee Reference', required=True, ondelete='cascade')
    name = fields.Char(string='Installment Name', required=True)
    due_date = fields.Date(string='Due Date', required=True)
    amount_percentage = fields.Float(string='Percentage (%)', required=True)
    amount = fields.Float(string='Amount', compute='_compute_amount', store=True)
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled')
    ], string='Status', compute='_compute_state', store=True, default='draft')

    @api.depends('student_fee_id.net_amount', 'amount_percentage')
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.student_fee_id.net_amount * (rec.amount_percentage / 100.0)

    @api.depends('invoice_id', 'invoice_id.payment_state', 'invoice_id.state')
    def _compute_state(self):
        for rec in self:
            if rec.invoice_id:
                if rec.invoice_id.payment_state == 'paid':
                    rec.state = 'paid'
                elif rec.invoice_id.state == 'cancel':
                    rec.state = 'cancelled'
                else:
                    rec.state = 'invoiced'
            else:
                rec.state = 'draft'

    def action_create_invoice(self):
        for rec in self:
            if rec.invoice_id:
                raise ValidationError(_("Invoice is already created for this installment."))
            
            line_vals = []
            structure = rec.student_fee_id.structure_id
            pct = rec.amount_percentage / 100.0

            for line in structure.line_ids:
                line_vals.append({
                    'name': f"{line.name} ({rec.name} - {rec.amount_percentage}%)",
                    'product_id': line.product_id.id,
                    'quantity': 1,
                    'price_unit': line.amount * pct,
                })

            if rec.student_fee_id.discount > 0:
                prod = structure.line_ids[0].product_id if structure.line_ids else False
                line_vals.append({
                    'name': f"{_('Discount Allowed')} ({rec.name})",
                    'product_id': prod.id if prod else False,
                    'quantity': 1,
                    'price_unit': -rec.student_fee_id.discount * pct,
                })

            if rec.student_fee_id.scholarship > 0:
                prod = structure.line_ids[0].product_id if structure.line_ids else False
                schol_amount = (rec.student_fee_id.amount - rec.student_fee_id.discount) * (rec.student_fee_id.scholarship / 100.0)
                line_vals.append({
                    'name': f"{_('Scholarship')} ({rec.student_fee_id.scholarship}%) ({rec.name})",
                    'product_id': prod.id if prod else False,
                    'quantity': 1,
                    'price_unit': -schol_amount * pct,
                })

            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': rec.student_fee_id.student_id.partner_id.id,
                'invoice_date': fields.Date.context_today(rec),
                'invoice_line_ids': [(0, 0, l) for l in line_vals],
                'company_id': rec.student_fee_id.company_id.id,
            }
            invoice = self.env['account.move'].create(invoice_vals)
            invoice.action_post()
            rec.write({
                'invoice_id': invoice.id,
                'state': 'invoiced'
            })

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return
        return {
            'name': _("Invoice"),
            'view_mode': 'form',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'type': 'ir.actions.act_window',
            'context': {'create': False},
        }