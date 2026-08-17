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
    
    exam_result_ids = fields.One2many('school.exam.result', 'student_id', string='Exam Results')
    gpa = fields.Float(string='GPA', compute='_compute_gpa', store=True)

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
