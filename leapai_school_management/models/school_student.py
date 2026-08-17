# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import date


class SchoolStudent(models.Model):
    _name = 'school.student'
    _description = 'School Student'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Student Name', required=True, tracking=True)
    code = fields.Char(string='Student ID', readonly=True, copy=False, default='New')
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    academic_year_id = fields.Many2one(
        'school.academic.year',
        string='Academic Year',
        related='class_id.academic_year_id',
        store=True,
    )
    partner_id = fields.Many2one('res.partner', string='Contact')
    date_of_birth = fields.Date(string='Date of Birth')
    age = fields.Integer(string='Age', compute='_compute_age', store=False)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], string='Gender')
    blood_group = fields.Selection([
        ('A+', 'A+'), ('A-', 'A-'),
        ('B+', 'B+'), ('B-', 'B-'),
        ('O+', 'O+'), ('O-', 'O-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'),
    ], string='Blood Group')
    nationality = fields.Many2one('res.country', string='Nationality')
    religion = fields.Char(string='Religion')
    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')
    address = fields.Text(string='Address')
    image = fields.Binary(string='Photo')
    father_name = fields.Char(string="Father's Name")
    father_phone = fields.Char(string="Father's Phone")
    father_occupation = fields.Char(string="Father's Occupation")
    mother_name = fields.Char(string="Mother's Name")
    mother_phone = fields.Char(string="Mother's Phone")
    guardian_name = fields.Char(string='Guardian Name')
    guardian_phone = fields.Char(string='Guardian Phone')
    guardian_relation = fields.Char(string='Guardian Relation')
    admission_date = fields.Date(string='Admission Date', default=fields.Date.today)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('enrolled', 'Enrolled'),
        ('active', 'Active'),
        ('graduated', 'Graduated'),
        ('expelled', 'Expelled'),
    ], string='Status', default='draft', tracking=True)
    fee_payment_ids = fields.One2many('school.fee.payment', 'student_id', string='Fee Payments')
    exam_result_ids = fields.One2many('school.exam.result', 'student_id', string='Exam Results')
    attendance_ids = fields.One2many('school.attendance', 'student_id', string='Attendance')
    hostel_allocation_id = fields.Many2one('school.hostel.allocation', string='Hostel Allocation')
    transport_route_id = fields.Many2one('school.transport.route', string='Transport Route')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    fee_paid = fields.Monetary(
        string='Total Fees Paid',
        compute='_compute_fees',
        currency_field='currency_id',
        store=False,
    )
    fee_due = fields.Monetary(
        string='Fees Due',
        compute='_compute_fees',
        currency_field='currency_id',
        store=False,
    )
    note = fields.Text(string='Notes')

    @api.depends('date_of_birth')
    def _compute_age(self):
        today = date.today()
        for record in self:
            if record.date_of_birth:
                dob = record.date_of_birth
                record.age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            else:
                record.age = 0

    @api.depends('fee_payment_ids', 'fee_payment_ids.amount', 'fee_payment_ids.state')
    def _compute_fees(self):
        for record in self:
            paid_payments = record.fee_payment_ids.filtered(lambda p: p.state == 'paid')
            record.fee_paid = sum(paid_payments.mapped('amount'))
            all_structures = self.env['school.fee.structure'].search([
                ('class_id', '=', record.class_id.id),
            ])
            total_due = sum(all_structures.mapped('amount'))
            record.fee_due = max(0, total_due - record.fee_paid)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('school.student') or 'New'
        return super().create(vals_list)

    def action_enroll(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft students can be enrolled.'))
            record.state = 'enrolled'

    def action_activate(self):
        for record in self:
            if record.state != 'enrolled':
                raise UserError(_('Only enrolled students can be activated.'))
            record.state = 'active'

    def action_graduate(self):
        for record in self:
            if record.state not in ('active', 'enrolled'):
                raise UserError(_('Only active or enrolled students can be graduated.'))
            record.state = 'graduated'

    def action_expel(self):
        for record in self:
            if record.state == 'expelled':
                raise UserError(_('Student is already expelled.'))
            record.state = 'expelled'

    def action_reset(self):
        for record in self:
            record.state = 'draft'

    def action_view_exams(self):
        return {
            'name': _('Exam Results'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.exam.result',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
        }

    def action_view_fees(self):
        return {
            'name': _('Fee Payments'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.fee.payment',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
        }

    def action_view_attendance(self):
        return {
            'name': _('Attendance'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.attendance',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
        }
