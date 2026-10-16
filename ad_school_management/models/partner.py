from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_student = fields.Boolean(string='Is Student', default=False)
    is_parent = fields.Boolean(string='Is Parent', default=False)

    # Transport staff
    is_school_driver = fields.Boolean(string='Is Driver', default=False)
    is_school_caretaker = fields.Boolean(string='Is Caretaker', default=False)
    driver_type = fields.Selection([
        ('own', 'Own Driver (School Payroll)'),
        ('outside', 'Outside Driver (Vendor / Contract)'),
    ], string='Driver Type', default='own')
    driving_license_no = fields.Char(string='Driving License No.')
    driving_license_expiry = fields.Date(string='License Expiry Date')

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
    mother_tongue = fields.Selection([
        ('english', 'English'),
        ('malayalam', 'Malayalam'),
        ('tamil', 'Tamil'),
        ('hindi', 'Hindi'),
        ('other', 'Other'),
    ], string='Mother Tongue')
    emergency_contact = fields.Char(string='Emergency Contact')
    medical_notes = fields.Text(string='Medical Notes')
    hobbies = fields.Text(string='Hobbies & Interests')
    date_of_leaving = fields.Date(string='Date of Leaving')
    reason_for_leaving = fields.Text(string='Reason for Leaving')
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
    school_parent_ids = fields.One2many('school.parent', 'partner_id', string='Parent Records')