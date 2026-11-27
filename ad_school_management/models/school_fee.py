from odoo import models, fields, api, _, Command
from odoo.exceptions import ValidationError

FEE_TYPES = [
    ('general', 'General (all students)'),
    ('transport', 'Transport (students with a route)'),
    ('hostel', 'Hostel (students with a room)'),
]


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
    total_amount = fields.Float(string='General Total', compute='_compute_total_amount', store=True,
                                help="Total of the General components. Transport and Hostel components are added "
                                     "per student (stop amount / room rent x months).")

    _code_uniq = models.Constraint(
        'unique(code)', 'The fee structure code must be unique!'
    )

    @api.model_create_multi
    def create(self, vals_list):
        structures = super().create(vals_list)
        structures._sync_students()
        return structures

    def write(self, vals):
        res = super().write(vals)
        if {'class_ids', 'academic_year_id', 'line_ids'} & set(vals):
            self._sync_students()
        return res

    def _sync_students(self):
        """Create / update the fees of the students of the structure's classes."""
        for structure in self:
            if structure.class_ids and structure.academic_year_id:
                self.env['school.student'].sudo().search([
                    ('class_id', 'in', structure.class_ids.ids),
                    ('academic_year_id', '=', structure.academic_year_id.id),
                    ('student_status', 'in', ('approved', 'enrolled')),
                ])._sync_student_fees()

    @api.depends('line_ids.amount', 'line_ids.fee_type')
    def _compute_total_amount(self):
        for struct in self:
            struct.total_amount = sum(struct.line_ids.filtered(lambda l: l.fee_type == 'general').mapped('amount'))

    def _student_components(self, student):
        """The fee components of this structure that apply to one student, with their amounts.

        General   : the component amount, for every student.
        Transport : boarding stop Monthly Amount x months, only when the student has a route and a stop.
        Hostel    : room Monthly Rent x months, only when the student has a hostel room.
        """
        self.ensure_one()
        components = []
        for line in self.line_ids:
            if line.fee_type == 'transport':
                stop = student.van_boarding_point_id if student.transport_route_id else False
                if not stop or stop.amount <= 0:
                    continue
                rate, months = stop.amount, line.months
                amount = rate * months
                name = _("%(name)s - %(stop)s", name=line.name, stop=stop.name)
            elif line.fee_type == 'hostel':
                room = student.hostel_room_id
                if not room or room.rent <= 0:
                    continue
                rate, months = room.rent, line.months
                amount = rate * months
                name = _("%(name)s - %(room)s", name=line.name, room=room.display_name)
            else:
                amount = line.amount
                name = line.name
                rate, months = 0.0, 0
            components.append({
                'name': name,
                'fee_type': line.fee_type,
                'product_id': line.product_id.id,
                'amount': amount,
                'rate': rate,
                'months': months,
                'structure_line_id': line.id,
            })
        return components

class SchoolFeeStructureLine(models.Model):
    _name = 'school.fee.structure.line'
    _description = 'Fee Structure Line'

    fee_structure_id = fields.Many2one('school.fee.structure', string='Fee Structure', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    fee_type = fields.Selection(FEE_TYPES, string='Fee Type', default='general', required=True,
                                help="General: every student. Transport: only students with a transport route "
                                     "(boarding stop Monthly Amount x Months). Hostel: only students with a hostel room "
                                     "(room Monthly Rent x Months).")
    name = fields.Char(string='Component Name', required=True)
    amount = fields.Float(string='Amount', required=True, default=0.0,
                          help="Used for General components only.")
    months = fields.Integer(string='Months', default=10,
                            help="Transport / Hostel: number of months billed in this structure.")
    product_id = fields.Many2one('product.product', string='Product Reference', required=True)

    @api.constrains('amount', 'months', 'fee_type')
    def _check_amount(self):
        for line in self:
            if line.fee_type == 'general' and line.amount <= 0:
                raise ValidationError(_("Component amount must be greater than zero (%s).") % line.name)
            if line.fee_type in ('transport', 'hostel') and line.months <= 0:
                raise ValidationError(_("Months must be greater than zero (%s).") % line.name)

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
        for structure in self.mapped('fee_structure_id'):
            total = sum(structure.installment_ids.mapped('amount_percentage'))
            if round(total, 2) > 100:
                raise ValidationError(_(
                    "The installments of %(structure)s add up to %(total)s%%. They must not be more than 100%%.",
                    structure=structure.name, total=round(total, 2)))

class SchoolStudentFee(models.Model):
    _name = 'school.student.fee'
    _description = 'Student Fee'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Fee Reference', required=True, readonly=True, default='/', copy=False)
    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True)
    structure_id = fields.Many2one('school.fee.structure', string='Fee Structure', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', related='structure_id.academic_year_id', store=True)
    class_id = fields.Many2one('school.class', string='Class', compute='_compute_class_id', store=True,
                               readonly=False, help="Choose the class first to list only its students.")
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
    line_ids = fields.One2many('school.student.fee.line', 'student_fee_id', string='Fee Components', copy=True)
    has_invoice = fields.Boolean(compute='_compute_has_invoice')
    unplanned_percentage = fields.Float(
        string='Not in Installments (%)', compute='_compute_unplanned_percentage',
        help="Part of the fee that no installment covers yet (installments add up to less than 100%).")

    _student_struct_uniq = models.Constraint(
        'unique(student_id, structure_id)', 'This fee structure is already assigned to this student!'
    )

    @api.depends('student_id.class_id')
    def _compute_class_id(self):
        for fee in self:
            # with a student the class follows the student; without one, keep the class chosen
            fee.class_id = fee.student_id.class_id if fee.student_id else fee.class_id

    @api.onchange('class_id')
    def _onchange_class_id(self):
        # class changed: drop a student / structure that does not belong to it
        if self.student_id and self.student_id.class_id != self.class_id:
            self.student_id = False
        if self.structure_id.class_ids and self.class_id not in self.structure_id.class_ids:
            self.structure_id = False

    @api.constrains('student_id', 'structure_id')
    def _check_structure_class(self):
        """A fee structure with Applicable Classes can only be given to students of those classes."""
        for fee in self:
            classes = fee.structure_id.class_ids
            if classes and fee.student_id.class_id not in classes:
                raise ValidationError(_(
                    "%(structure)s is for %(classes)s, but %(student)s is in %(cls)s. "
                    "Choose the fee structure of the student's class.",
                    structure=fee.structure_id.name, classes=', '.join(classes.mapped('name')),
                    student=fee.student_id.name, cls=fee.student_id.class_id.name or _('no class')))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.student.fee.seq') or '/'
            if not vals.get('company_id'):
                student = self.env['school.student'].browse(vals.get('student_id'))
                vals['company_id'] = student.company_id.id or self.env.company.id
            # NEW: take the student's scholarship unless a discount/scholarship was given
            if vals.get('student_id') and 'discount' not in vals and 'scholarship' not in vals:
                student = self.env['school.student'].browse(vals['student_id'])
                vals['discount'] = student._get_scholarship_discount()
        records = super(SchoolStudentFee, self).create(vals_list)
        for record in records:
            if not record.line_ids:
                record._generate_fee_lines()
            record._generate_installments()
        records._sync_draft_invoices()
        return records

    def write(self, vals):
        if 'student_id' in vals and not vals.get('company_id'):
            student = self.env['school.student'].browse(vals['student_id'])
            vals['company_id'] = student.company_id.id or self.env.company.id
        res = super(SchoolStudentFee, self).write(vals)
        if 'structure_id' in vals:
            for record in self:
                if not record.has_invoice:
                    record.line_ids.unlink()
                    record._generate_fee_lines()
                open_lines = record.installment_line_ids.filtered(
                    lambda i: not i.invoice_id or i.invoice_id.state == 'draft')
                open_lines._drop_draft_invoices()
                open_lines.unlink()
                record._generate_installments()
        if {'structure_id', 'discount', 'scholarship'} & set(vals):
            self._sync_draft_invoices()
        return res

    def unlink(self):
        self.mapped('installment_line_ids')._drop_draft_invoices()
        return super().unlink()

    @api.depends('installment_line_ids.invoice_id', 'installment_line_ids.invoice_id.state')
    def _compute_has_invoice(self):
        # only confirmed (posted / cancelled) invoices lock the fee; draft invoices follow the fee
        for rec in self:
            rec.has_invoice = bool(rec.installment_line_ids.filtered(
                lambda i: i.invoice_id and i.invoice_id.state != 'draft'))

    def _sync_draft_invoices(self):
        """Keep one draft invoice per not-yet-invoiced installment, so the fee shows in Invoicing
        right away. Draft invoices are rebuilt whenever the fee changes; confirmed ones are left alone."""
        for rec in self:
            for inst in rec.installment_line_ids:
                if inst.invoice_id and inst.invoice_id.state != 'draft':
                    continue
                inst._drop_draft_invoices()
                try:
                    with self.env.cr.savepoint():
                        inst._create_draft_invoice()
                except Exception as error:  # e.g. accounting not set up for the company yet
                    rec.message_post(body=_("Draft invoice for %(inst)s could not be created: %(err)s",
                                            inst=inst.name, err=error))

    def _generate_fee_lines(self):
        """Copy the structure components that apply to the student (amounts frozen at that moment)."""
        Line = self.env['school.student.fee.line']
        for rec in self:
            if rec.structure_id and rec.student_id:
                Line.create([dict(comp, student_fee_id=rec.id)
                             for comp in rec.structure_id._student_components(rec.student_id)])

    def _get_components(self):
        """Fee components to invoice. Fees created before components existed get them on first use."""
        self.ensure_one()
        if not self.line_ids:
            self._generate_fee_lines()
        return self.line_ids

    def _recompute_components(self):
        """Rebuild the components from the structure and the student's current route / room / scholarship."""
        for rec in self:
            if rec.has_invoice:
                continue
            # months reduced / changed by hand on transport / hostel lines are kept
            kept_months = {l.structure_line_id.id: l.months for l in rec.line_ids
                           if l.fee_type in ('transport', 'hostel') and l.structure_line_id and l.rate
                           and l.months != l.structure_line_id.months}
            rec.line_ids.unlink()
            rec._generate_fee_lines()
            for line in rec.line_ids:
                if line.structure_line_id.id in kept_months:
                    line.with_context(skip_fee_sync=True).months = kept_months[line.structure_line_id.id]
            if not rec.discount:
                # scholarship given to the student after the fee was created
                rec.discount = rec.student_id._get_scholarship_discount()
            rec._sync_draft_invoices()

    def action_refresh_components(self):
        """Recalculate the components from the structure (e.g. after the student's route changed)."""
        for rec in self:
            if rec.has_invoice:
                raise ValidationError(_(
                    "%s already has an invoice. Components can only be recalculated before invoicing.") % rec.name)
            rec._recompute_components()
            rec.message_post(body=_("Fee components recalculated from %s.") % rec.structure_id.name)
        return True

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
            # installment plan below 100%: the rest becomes a "Balance" installment
            rec._add_balance_installment()

    @api.depends('installment_line_ids.amount_percentage', 'installment_line_ids.state')
    def _compute_unplanned_percentage(self):
        for rec in self:
            planned = sum(rec.installment_line_ids.filtered(lambda i: i.state != 'cancelled')
                          .mapped('amount_percentage'))
            rec.unplanned_percentage = max(round(100.0 - planned, 2), 0.0)

    def _add_balance_installment(self):
        Installment = self.env['school.student.fee.installment']
        for rec in self:
            if rec.unplanned_percentage > 0.009:
                Installment.create({
                    'student_fee_id': rec.id,
                    'name': _("Balance Payment"),
                    'due_date': fields.Date.context_today(rec),
                    'amount_percentage': rec.unplanned_percentage,
                })

    def action_add_balance_installment(self):
        """Add an installment for the part of the fee no installment covers, so it can be invoiced and paid."""
        for rec in self:
            if rec.unplanned_percentage <= 0.009:
                raise ValidationError(_("%s: the installments already cover the whole fee.") % rec.name)
            rec._add_balance_installment()
            rec._sync_draft_invoices()
            rec.message_post(body=_("Balance Payment installment added for the remaining fee."))
        return True

    # NEW: when a student is selected on the fee form, fill the scholarship discount
    @api.onchange('student_id')
    def _onchange_student_id_scholarship(self):
        if self.student_id:
            self.discount = self.student_id._get_scholarship_discount()

    @api.constrains('discount', 'scholarship')
    def _check_discount_scholarship(self):
        for fee in self:
            if fee.discount < 0:
                raise ValidationError(_("Discount cannot be negative."))
            if fee.scholarship < 0 or fee.scholarship > 100:
                raise ValidationError(_(
                    "Scholarship is a percentage and must be between 0 and 100 (%s: %s). "
                    "To reduce a fixed amount, use Discount (Flat) instead.") % (fee.student_id.name, fee.scholarship))

    @api.depends('line_ids.amount', 'structure_id.total_amount')
    def _compute_amount(self):
        for fee in self:
            # fees created before components existed: the structure total
            fee.amount = sum(fee.line_ids.mapped('amount')) if fee.line_ids else fee.structure_id.total_amount

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

    @api.depends('installment_line_ids.state', 'installment_line_ids.amount_percentage')
    def _compute_state_from_invoice(self):
        for rec in self:
            if rec.installment_line_ids:
                states = rec.installment_line_ids.mapped('state')
                if all(s == 'draft' for s in states):
                    rec.state = 'draft'
                elif all(s == 'paid' for s in states) and rec.unplanned_percentage <= 0.009:
                    rec.state = 'paid'
                elif all(s == 'cancelled' for s in states):
                    rec.state = 'cancelled'
                else:
                    rec.state = 'invoiced'
            else:
                rec.state = 'draft'

    def action_create_invoice(self):
        for rec in self:
            uninvoiced = rec.installment_line_ids.filtered(
                lambda i: not i.invoice_id or i.invoice_id.state == 'draft')
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

class SchoolStudentFeeLine(models.Model):
    _name = 'school.student.fee.line'
    _description = 'Student Fee Component'
    _order = 'student_fee_id, id'

    student_fee_id = fields.Many2one('school.student.fee', string='Student Fee', required=True, ondelete='cascade')
    structure_line_id = fields.Many2one('school.fee.structure.line', string='Structure Component', ondelete='set null')
    name = fields.Char(string='Component', required=True)
    fee_type = fields.Selection(FEE_TYPES, string='Fee Type', default='general', required=True)
    product_id = fields.Many2one('product.product', string='Product')
    rate = fields.Float(string='Monthly Rate', help="Stop Monthly Amount / room Monthly Rent.")
    months = fields.Integer(string='Months',
                            help="Months charged. Reduce it when the student did not use transport / hostel "
                                 "for some months; the amount follows.")
    amount = fields.Float(string='Amount')

    @api.onchange('months')
    def _onchange_months(self):
        if self.fee_type in ('transport', 'hostel'):
            self.amount = self.rate * self.months

    @api.constrains('months')
    def _check_months(self):
        for line in self:
            if line.fee_type in ('transport', 'hostel') and not 0 <= line.months <= 12:
                raise ValidationError(_("Months must be between 0 and 12 (%s).") % line.name)

    def write(self, vals):
        if 'months' in vals and self.mapped('student_fee_id').filtered('has_invoice'):
            raise ValidationError(_("This fee is already invoiced. Use a credit note to reduce it."))
        res = super().write(vals)
        if 'months' in vals:
            for line in self.filtered(lambda l: l.fee_type in ('transport', 'hostel')):
                super(SchoolStudentFeeLine, line).write({'amount': line.rate * line.months})
            if not self.env.context.get('skip_fee_sync'):
                for fee in self.mapped('student_fee_id'):
                    fee._sync_draft_invoices()
                    fee.message_post(body=_("Months changed on %s.") % ', '.join(
                        '%s: %s' % (l.name, l.months) for l in self if l.student_fee_id == fee))
        return res


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
            if rec.invoice_id and rec.invoice_id.state != 'draft':
                if rec.invoice_id.payment_state == 'paid':
                    rec.state = 'paid'
                elif rec.invoice_id.state == 'cancel':
                    rec.state = 'cancelled'
                else:
                    rec.state = 'invoiced'
            else:
                rec.state = 'draft'

    def _drop_draft_invoices(self):
        drafts = self.mapped('invoice_id').filtered(lambda m: m.state == 'draft')
        if drafts:
            self.filtered(lambda i: i.invoice_id in drafts).write({'invoice_id': False})
            drafts.unlink()

    def _create_draft_invoice(self):
        for rec in self:
            invoice = self.env['account.move'].create(rec._prepare_invoice_vals())
            rec.invoice_id = invoice

    def action_create_invoice(self):
        """Confirm the installment's invoice (the draft one when it exists)."""
        for rec in self:
            if rec.invoice_id and rec.invoice_id.state != 'draft':
                raise ValidationError(_("Invoice is already created for this installment."))
            if not rec.invoice_id:
                rec._create_draft_invoice()
            invoice = rec.invoice_id
            if not invoice.invoice_date:
                invoice.invoice_date = fields.Date.context_today(rec)
            invoice.action_post()

    def _prepare_invoice_vals(self):
        self.ensure_one()
        rec = self
        line_vals = []
        components = rec.student_fee_id._get_components()
        pct = rec.amount_percentage / 100.0

        for line in components:
            label = line.name
            if line.fee_type in ('transport', 'hostel'):
                label = f"{line.name} ({line.rate:.2f} x {line.months} months)"
            line_vals.append({
                'name': f"{label} ({rec.name} - {rec.amount_percentage}%)",
                'product_id': line.product_id.id,
                'quantity': 1,
                'price_unit': line.amount * pct,
            })

        if rec.student_fee_id.discount > 0:
            prod = components[:1].product_id
            line_vals.append({
                'name': f"{_('Discount Allowed')} ({rec.name})",
                'product_id': prod.id if prod else False,
                'quantity': 1,
                'price_unit': -rec.student_fee_id.discount * pct,
            })

        if rec.student_fee_id.scholarship > 0:
            prod = components[:1].product_id
            schol_amount = (rec.student_fee_id.amount - rec.student_fee_id.discount) * (rec.student_fee_id.scholarship / 100.0)
            line_vals.append({
                'name': f"{_('Scholarship')} ({rec.student_fee_id.scholarship}%) ({rec.name})",
                'product_id': prod.id if prod else False,
                'quantity': 1,
                'price_unit': -schol_amount * pct,
            })

        return {
            'move_type': 'out_invoice',
            'partner_id': rec.student_fee_id.student_id.partner_id.id,
            'invoice_date_due': rec.due_date,
            'invoice_origin': '%s - %s' % (rec.student_fee_id.name, rec.name),
            'invoice_line_ids': [(0, 0, l) for l in line_vals],
            'company_id': rec.student_fee_id.company_id.id,
        }

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
        self._load_students()

    @api.onchange('section_id', 'structure_id', 'apply_scholarship')
    def _onchange_load_students(self):
        self._load_students()

    def _student_domain(self):
        domain = [
            ('class_id', '=', self.class_id.id),
            ('academic_year_id', '=', self.academic_year_id.id),
            ('student_status', 'in', ('approved', 'enrolled')),
        ]
        if self.section_id:
            domain.append(('section_id', '=', self.section_id.id))
        return domain

    def _student_line_commands(self, students):
        assigned = self.env['school.student.fee'].search([
            ('student_id', 'in', students.ids), ('structure_id', '=', self.structure_id.id)]).mapped('student_id') \
            if self.structure_id else self.env['school.student']
        return [Command.clear()] + [Command.create({
            'student_id': st.id,
            'discount': self._scholarship_discount(st),
            'already_assigned': st in assigned,
            'selected': st not in assigned,
        }) for st in students]

    def _load_students(self):
        """List the students as soon as class, academic year and fee structure are chosen."""
        for wiz in self:
            if not (wiz.class_id and wiz.academic_year_id and wiz.structure_id):
                wiz.line_ids = [Command.clear()]
                continue
            students = self.env['school.student'].search(wiz._student_domain(), order='section_id, roll_number, name')
            wiz.line_ids = wiz._student_line_commands(students)

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
        return student._get_scholarship_discount() if self.apply_scholarship else 0.0

    def action_fetch_students(self):
        self.ensure_one()
        students = self.env['school.student'].search(self._student_domain(), order='section_id, roll_number, name')
        if not students:
            raise ValidationError(_("No approved or enrolled students found for this class / section / academic year."))
        self.line_ids = self._student_line_commands(students)
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
    gross_amount = fields.Float(string='Total', compute='_compute_net_amount',
                                help="General components + transport / hostel for this student.")
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

    @api.depends('wizard_id.structure_id', 'student_id', 'discount', 'scholarship')
    def _compute_net_amount(self):
        for line in self:
            structure = line.wizard_id.structure_id
            gross = sum(c['amount'] for c in structure._student_components(line.student_id)) \
                if structure and line.student_id else 0.0
            line.gross_amount = gross
            net = gross - line.discount
            if line.scholarship:
                net = net * (1.0 - line.scholarship / 100.0)
            line.net_amount = max(net, 0.0)