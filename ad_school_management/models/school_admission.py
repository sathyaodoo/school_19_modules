from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolAdmission(models.Model):
    _name = 'school.admission'
    _description = 'Admission Application'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Application Number', required=True, readonly=True, default='/', copy=False)
    
    first_name = fields.Char(string='First Name', required=True, tracking=True)
    last_name = fields.Char(string='Last Name', required=True, tracking=True)
    date_of_birth = fields.Date(string='Date of Birth', required=True, tracking=True)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string='Gender', required=True, default='male', tracking=True)
    email = fields.Char(string='Email', tracking=True)
    phone = fields.Char(string='Phone', tracking=True)
    
    street = fields.Char(string='Street')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    country_id = fields.Many2one('res.country', string='Country')
    zip = fields.Char(string='Zip')

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', tracking=True)
    
    parent_name = fields.Char(string='Parent Name', tracking=True)
    parent_phone = fields.Char(string='Parent Phone', tracking=True)
    parent_email = fields.Char(string='Parent Email', tracking=True)
    parent_relation = fields.Selection([
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('guardian', 'Guardian')
    ], string='Parent Relation', default='father', tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('enrolled', 'Enrolled'),
        ('rejected', 'Rejected')
    ], string='Status', default='draft', required=True, tracking=True)

    student_id = fields.Many2one('school.student', string='Student Profile', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.admission.seq') or '/'
        return super(SchoolAdmission, self).create(vals_list)

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        for record in self:
            if not record.section_id:
                raise ValidationError(_("Please assign a Section before approving the admission."))
            
            student_partner_vals = {
                'name': f"{record.first_name} {record.last_name}",
                'email': record.email,
                'phone': record.phone,
                'street': record.street,
                'city': record.city,
                'state_id': record.state_id.id,
                'country_id': record.country_id.id,
                'zip': record.zip,
                'date_of_birth': record.date_of_birth,
                'gender': record.gender,
                'is_student': True,
                'student_status': 'approved',
                'company_id': record.company_id.id,
            }
            student_partner = self.env['res.partner'].create(student_partner_vals)

            student_vals = {
                'partner_id': student_partner.id,
                'class_id': record.class_id.id,
                'section_id': record.section_id.id,
                'academic_year_id': record.academic_year_id.id,
            }
            student = self.env['school.student'].create(student_vals)

            if record.parent_name:
                parent_partner_vals = {
                    'name': record.parent_name,
                    'phone': record.parent_phone,
                    'email': record.parent_email,
                    'is_parent': True,
                    'company_id': record.company_id.id,
                }
                parent_partner = self.env['res.partner'].create(parent_partner_vals)
                
                parent_vals = {
                    'partner_id': parent_partner.id,
                    'relation': record.parent_relation,
                    'student_ids': [(4, student.id)],
                }
                parent = self.env['school.parent'].create(parent_vals)
                student.write({'parent_ids': [(4, parent.id)]})

            record.write({
                'state': 'approved',
                'student_id': student.id
            })

    def action_enroll(self):
        for record in self:
            if not record.student_id:
                raise ValidationError(_("No student record found for enrollment."))
            record.student_id.write({'student_status': 'enrolled'})
            record.write({'state': 'enrolled'})

    def action_reject(self):
        self.write({'state': 'rejected'})
