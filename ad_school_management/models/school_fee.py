from odoo import models, fields, api, _, Command
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
    class_ids = fields.Many2many('school.class', 'school_fee_structure_class_rel', 'structure_id', 'class_id',
                                 string='Applicable Classes',
                                 help="Classes this fee structure is used for. Used by 'Generate Class Fees'.")
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
    class_id = fields.Many2one('school.class', string='Class', related='student_id.class_id', store=True)
    section_id = fields.Many2one('school.section', string='Section', related='student_id.section_id', store=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    amount = fields.Float(string='Structure Total', compute='_compute_amount', store=True)
    discount = fields.Float(string='Discount (Flat)', default=0.0, tracking=True)
    scholarship = fields.Float(string='Scholarship (%)', default=0.0, tracking=True)
    net_amount = fields.Float(string='Net Amount', compute='_compute_net_amount', store=True)
    scholarship_value = fields.Float(string='Scholarship Amount', compute='_compute_net_amount', store=True,
                                     help="Scholarship % converted to an amount.")
    concession_amount = fields.Float(string='Total Concession', compute='_compute_net_amount', store=True,
                                     help="Discount + scholarship amount given on this fee.")
    paid_amount = fields.Float(string='Paid', compute='_compute_paid_amount')
    due_amount = fields.Float(string='Balance Due', compute='_compute_paid_amount')
    
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

    @api.constrains('discount', 'scholarship')
    def _check_discount_scholarship(self):
        for fee in self:
            if fee.discount < 0:
                raise ValidationError(_("Discount cannot be negative."))
            if fee.scholarship < 0 or fee.scholarship > 100:
                raise ValidationError(_(
                    "Scholarship is a percentage and must be between 0 and 100 (%s: %s). "
                    "To reduce a fixed amount, use Discount (Flat) instead.") % (fee.student_id.name, fee.scholarship))

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
            fee.scholarship_value = max(fee.amount - fee.discount, 0.0) * (fee.scholarship / 100.0)
            fee.concession_amount = fee.amount - fee.net_amount

    @api.depends('net_amount', 'installment_line_ids.invoice_id.amount_residual',
                 'installment_line_ids.invoice_id.state')
    def _compute_paid_amount(self):
        for fee in self:
            invoices = fee.installment_line_ids.mapped('invoice_id').filtered(lambda m: m.state == 'posted')
            fee.paid_amount = sum(invoices.mapped('amount_total')) - sum(invoices.mapped('amount_residual'))
            fee.due_amount = fee.net_amount - fee.paid_amount

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


class SchoolFeeGenerate(models.TransientModel):
    _name = 'school.fee.generate'
    _description = 'Generate Fees for a Class / Section'

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section',
                                 domain="[('class_id', '=', class_id)]",
                                 help="Leave empty to include every section of the class.")
    structure_id = fields.Many2one(
        'school.fee.structure', string='Fee Structure', required=True,
        domain="[('academic_year_id', '=', academic_year_id), '|', ('class_ids', '=', False), ('class_ids', 'in', class_id)]")
    structure_total = fields.Float(related='structure_id.total_amount', string='Structure Total')
    apply_scholarship = fields.Boolean(
        string='Apply Scholarship as Discount', default=True,
        help="Students with an active, non-expired sponsorship get their Scholarship Amount as a flat discount.")
    create_invoices = fields.Boolean(string='Create Invoices Immediately', default=False)
    line_ids = fields.One2many('school.fee.generate.line', 'wizard_id', string='Students')
    student_count = fields.Integer(compute='_compute_counts', string='Students')
    new_count = fields.Integer(compute='_compute_counts', string='To Generate')
    total_net = fields.Float(compute='_compute_counts', string='Total Net Amount')

    @api.depends('line_ids.selected', 'line_ids.already_assigned', 'line_ids.net_amount')
    def _compute_counts(self):
        for wiz in self:
            todo = wiz.line_ids.filtered(lambda l: l.selected and not l.already_assigned)
            wiz.student_count = len(wiz.line_ids)
            wiz.new_count = len(todo)
            wiz.total_net = sum(todo.mapped('net_amount'))

    @api.onchange('class_id', 'academic_year_id')
    def _onchange_class_year(self):
        if self.section_id and self.section_id.class_id != self.class_id:
            self.section_id = False
        self.line_ids = [Command.clear()]
        if self.class_id and self.academic_year_id:
            structures = self.env['school.fee.structure'].search([
                ('academic_year_id', '=', self.academic_year_id.id),
                ('class_ids', 'in', self.class_id.id)])
            self.structure_id = structures[:1] if len(structures) == 1 else False

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Generate Class Fees'),
        }

    def _scholarship_discount(self, student):
        today = fields.Date.context_today(self)
        if (self.apply_scholarship and student.sponsorship_status == 'active' and student.scholarship_amount
                and (not student.scholarship_expiry_date or student.scholarship_expiry_date >= today)):
            return student.scholarship_amount
        return 0.0

    def action_fetch_students(self):
        self.ensure_one()
        domain = [
            ('class_id', '=', self.class_id.id),
            ('academic_year_id', '=', self.academic_year_id.id),
            ('student_status', 'in', ('approved', 'enrolled')),
        ]
        if self.section_id:
            domain.append(('section_id', '=', self.section_id.id))
        students = self.env['school.student'].search(domain, order='section_id, roll_number, name')
        if not students:
            raise ValidationError(_("No approved or enrolled students found for this class / section / academic year."))
        assigned = self.env['school.student.fee'].search([
            ('student_id', 'in', students.ids), ('structure_id', '=', self.structure_id.id)]).mapped('student_id')
        self.line_ids = [Command.clear()] + [Command.create({
            'student_id': st.id,
            'discount': self._scholarship_discount(st),
            'already_assigned': st in assigned,
            'selected': st not in assigned,
        }) for st in students]
        return self._reopen()

    def action_generate(self):
        self.ensure_one()
        todo = self.line_ids.filtered(lambda l: l.selected and not l.already_assigned)
        if not todo:
            raise ValidationError(_("Nothing to generate. Fetch students first, or all selected students already have this fee structure."))
        fees = self.env['school.student.fee'].create([{
            'student_id': line.student_id.id,
            'structure_id': self.structure_id.id,
            'discount': line.discount,
            'scholarship': line.scholarship,
        } for line in todo])
        if self.create_invoices:
            fees.action_create_invoice()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Fees - %s') % self.class_id.name,
            'res_model': 'school.student.fee',
            'view_mode': 'list,form',
            'domain': [('id', 'in', fees.ids)],
            'target': 'current',
        }


class SchoolFeeGenerateLine(models.TransientModel):
    _name = 'school.fee.generate.line'
    _description = 'Generate Fees - Student Line'

    wizard_id = fields.Many2one('school.fee.generate', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Include', default=True)
    student_id = fields.Many2one('school.student', string='Student', required=True)
    admission_no = fields.Char(related='student_id.admission_no', string='Admission No.')
    section_id = fields.Many2one(related='student_id.section_id', string='Section')
    discount = fields.Float(string='Discount (Amount)')
    scholarship = fields.Float(string='Scholarship %')
    net_amount = fields.Float(string='Net Amount', compute='_compute_net_amount')
    already_assigned = fields.Boolean(string='Already Assigned', readonly=True)

    @api.constrains('discount', 'scholarship')
    def _check_values(self):
        for line in self:
            if line.discount < 0:
                raise ValidationError(_("Discount cannot be negative (%s).") % line.student_id.name)
            if line.scholarship < 0 or line.scholarship > 100:
                raise ValidationError(_(
                    "Scholarship %% must be between 0 and 100 (%s: %s). "
                    "To reduce a fixed amount, use the Discount (Amount) column.") % (line.student_id.name, line.scholarship))

    @api.depends('wizard_id.structure_id', 'discount', 'scholarship')
    def _compute_net_amount(self):
        for line in self:
            net = line.wizard_id.structure_id.total_amount - line.discount
            if line.scholarship:
                net = net * (1.0 - line.scholarship / 100.0)
            line.net_amount = max(net, 0.0)