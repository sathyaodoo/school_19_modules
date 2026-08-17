from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_student = fields.Boolean(string='Is Student', default=False)
    is_parent = fields.Boolean(string='Is Parent', default=False)

    roll_number = fields.Char(string='Roll Number')
    guardian_type = fields.Selection([
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('guardian', 'Guardian')
    ], string='Guardian Type')
    blood_group = fields.Selection([
        ('A+', 'A+'), ('A-', 'A-'),
        ('B+', 'B+'), ('B-', 'B-'),
        ('O+', 'O+'), ('O-', 'O-'),
        ('AB+', 'AB+'), ('AB-', 'AB-')
    ], string='Blood Group')
    date_of_birth = fields.Date(string='Date of Birth')
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string='Gender')
    nationality_id = fields.Many2one('res.country', string='Nationality')
    religion = fields.Char(string='Religion')
    caste = fields.Char(string='Caste')
    emergency_contact = fields.Char(string='Emergency Contact')
    medical_notes = fields.Text(string='Medical Notes')
    student_status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('enrolled', 'Enrolled'),
        ('promoted', 'Promoted'),
        ('alumni', 'Alumni'),
        ('inactive', 'Inactive')
    ], string='Student Status')

    student_ids = fields.One2many('school.student', 'partner_id', string='Student Records')
    parent_ids = fields.One2many('school.parent', 'partner_id', string='Parent Records')
