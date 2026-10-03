from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolStudent(models.Model):
    _name = 'school.student'
    _description = 'Student'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'res.partner': 'partner_id'}
    _order = 'roll_number, name'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True, ondelete='cascade')
    
    admission_no = fields.Char(string='Admission No.', readonly=True, copy=False)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    roll_number = fields.Char(string='Roll Number', tracking=True, copy=False)
    parent_ids = fields.Many2many('school.parent', 'school_student_parent_rel', 'student_id', 'parent_id', string='Parents/Guardians')
    
    transport_route_id = fields.Many2one('school.transport.route', string='Transport Route')
    transport_fee_ids = fields.One2many('school.student.transport.fee', 'student_id', string='Transport Fees')
    student_fee_ids = fields.One2many('school.student.fee', 'student_id', string='Fees')
    fee_total = fields.Float(string='Total Fee', compute='_compute_fee_summary')
    fee_concession_total = fields.Float(string='Scholarship / Discount Applied', compute='_compute_fee_summary')
    fee_paid_total = fields.Float(string='Paid', compute='_compute_fee_summary')
    fee_due_total = fields.Float(string='Balance Due', compute='_compute_fee_summary')
    route_change_request_ids = fields.One2many('school.transport.route.change.request', 'student_id', string='Route Change Requests')
    van_boarding_point_id = fields.Many2one(
        'school.transport.stop', string='Van Boarding Point',
        domain="[('route_id', '=', transport_route_id)]"
    )
    vehicle_id = fields.Many2one(
        'school.vehicle', string='Vehicle', related='transport_route_id.effective_vehicle_id',
        store=True, readonly=True,
        help="Vehicle currently serving the student's route (replacement vehicle during a breakdown).")
    parent_contact = fields.Char(string='Parent Contact', compute='_compute_parent_contact')
    
    exam_result_ids = fields.One2many('school.exam.result', 'student_id', string='Exam Results')
    gpa = fields.Float(string='GPA', compute='_compute_gpa', store=True)
    sibling_ids = fields.One2many('school.student.sibling', 'student_id', string='Siblings')
    sponsor_name = fields.Char(string='Sponsor Name')
    sponsor_type = fields.Selection([
        ('ngo', 'NGO'),
        ('individual', 'Individual'),
        ('corporate', 'Corporate'),
        ('other', 'Other'),
    ], string='Sponsor Type')
    sponsor_contact = fields.Char(string='Sponsor Contact')
    sponsorship_status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='Sponsorship Status')
    relationship_to_student = fields.Char(string='Relationship to Student')

    scholarship_amount = fields.Float(string='Scholarship Amount')
    scholarship_type = fields.Selection([
        ('merit', 'Merit'),
        ('need_based', 'Need-based'),
        ('sports', 'Sports'),
        ('other', 'Other'),
    ], string='Scholarship Type')
    scholarship_approved_date = fields.Date(string='Scholarship Approved Date')
    scholarship_expiry_date = fields.Date(string='Scholarship Expiry Date')
    merit_tag = fields.Selection([
        ('excellent', 'Excellent'),
        ('very_good', 'Very Good'),
        ('good', 'Good'),
    ], string='Merit Tag')

    photo = fields.Binary(related='partner_id.image_1920', readonly=False, string='Photo')
 
    _admission_no_uniq = models.Constraint(
        'unique(admission_no)', 'The admission number must be unique!'
    )

    @api.depends('exam_result_ids.gpa')
    def _compute_gpa(self):
        for student in self:
            results = student.exam_result_ids
            if results:
                student.gpa = sum(results.mapped('gpa')) / len(results)
            else:
                student.gpa = 0.0
 
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('admission_no'):
                vals['admission_no'] = self.env['ir.sequence'].next_by_code('school.student.admission') or '/'
            vals['is_student'] = True
            
            if 'student_status' not in vals:
                partner_id = vals.get('partner_id')
                if partner_id:
                    partner = self.env['res.partner'].browse(partner_id)
                    vals['student_status'] = partner.student_status or 'draft'
                else:
                    vals['student_status'] = 'draft'
        return super(SchoolStudent, self).create(vals_list)

    @api.constrains('roll_number', 'class_id', 'section_id', 'academic_year_id')
    def _check_roll_number(self):
        for student in self:
            if student.roll_number:
                duplicate = self.search([
                    ('id', '!=', student.id),
                    ('roll_number', '=', student.roll_number),
                    ('class_id', '=', student.class_id.id),
                    ('section_id', '=', student.section_id.id),
                    ('academic_year_id', '=', student.academic_year_id.id)
                ])
                if duplicate:
                    raise ValidationError(_(
                        "Roll number %s already exists in class %s, section %s for academic year %s!"
                    ) % (student.roll_number, student.class_id.name, student.section_id.name, student.academic_year_id.name))

    @api.constrains('class_id', 'section_id')
    def _check_section_capacity(self):
        for student in self:
            if student.section_id:
                student_count = self.search_count([
                    ('class_id', '=', student.class_id.id),
                    ('section_id', '=', student.section_id.id),
                    ('academic_year_id', '=', student.academic_year_id.id),
                    ('id', '!=', student.id)
                ])
                if student_count >= student.section_id.capacity:
                    raise ValidationError(_(
                        "Section %s has reached its maximum capacity of %s students!"
                    ) % (student.section_id.name, student.section_id.capacity))

    def action_view_partner(self):
        self.ensure_one()
        return {
            'name': _('Contact Details'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


    @api.depends('parent_ids', 'parent_ids.name', 'parent_ids.phone')
    def _compute_parent_contact(self):
        for student in self:
            student.parent_contact = ', '.join(
                '%s (%s)' % (parent.name, parent.phone) if parent.phone else parent.name
                for parent in student.parent_ids
            )


    @api.depends('student_fee_ids.amount', 'student_fee_ids.concession_amount',
                 'student_fee_ids.net_amount', 'student_fee_ids.paid_amount')
    def _compute_fee_summary(self):
        for student in self:
            fees = student.student_fee_ids.filtered(lambda f: f.state != 'cancelled')
            student.fee_total = sum(fees.mapped('amount'))
            student.fee_concession_total = sum(fees.mapped('concession_amount'))
            student.fee_paid_total = sum(fees.mapped('paid_amount'))
            student.fee_due_total = sum(fees.mapped('due_amount'))


class SchoolStudentSibling(models.Model):
    _name = 'school.student.sibling'
    _description = 'Student Sibling Record'

    student_id = fields.Many2one('school.student', string='Student', required=True, ondelete='cascade')

    sibling_student_id = fields.Many2one(
        'school.student', string='Select Student', required=True,
        domain="[('id', '!=', student_id)]"
    )
    sibling_class_id = fields.Many2one('school.class', string='Sibling Class')
    sibling_section_id = fields.Many2one('school.section', string='Sibling Section')
    sibling_admission_no = fields.Char(string='Sibling Admission Number')
    relation_type = fields.Selection([
        ('brother', 'Brother'),
        ('sister', 'Sister'),
    ], string='Relation Type', required=True)

    mirror_id = fields.Many2one('school.student.sibling', string='Mirror Record', copy=False, readonly=True)

    @api.onchange('sibling_student_id')
    def _onchange_sibling_student_id(self):
        if self.sibling_student_id:
            self.sibling_class_id = self.sibling_student_id.class_id
            self.sibling_section_id = self.sibling_student_id.section_id
            self.sibling_admission_no = self.sibling_student_id.admission_no

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_sibling_mirror'):
            for record in records:
                if record.sibling_student_id and not record.mirror_id:
                    record._create_mirror_sibling()
        return records

    def _create_mirror_sibling(self):
        self.ensure_one()
        owner = self.student_id
        if owner.gender == 'male':
            mirror_relation = 'brother'
        elif owner.gender == 'female':
            mirror_relation = 'sister'
        else:
            

            mirror_relation = self.relation_type

        mirror = self.env['school.student.sibling'].with_context(skip_sibling_mirror=True).create({
            'student_id': self.sibling_student_id.id,
            'sibling_student_id': owner.id,
            'sibling_class_id': owner.class_id.id,
            'sibling_section_id': owner.section_id.id,
            'sibling_admission_no': owner.admission_no,
            'relation_type': mirror_relation,
            'mirror_id': self.id,
        })
        self.mirror_id = mirror.id

    def unlink(self):
        mirrors = self.mapped('mirror_id')
        res = super().unlink()
        if mirrors and not self.env.context.get('skip_sibling_mirror'):
            mirrors.with_context(skip_sibling_mirror=True).unlink()
        return res