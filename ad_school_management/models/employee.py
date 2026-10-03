from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    teacher_code = fields.Char(string='Teacher Code')
    qualification = fields.Char(string='Qualification')
    specialization = fields.Char(string='Specialization')
    joining_date = fields.Date(string='Joining Date')
    class_teacher_for = fields.Many2one('school.class', string='Class Teacher For')
    teacher_id = fields.Many2one('school.teacher', string='Teacher Profile')
    teacher_type = fields.Selection([
        ('teaching', 'Teaching Staff'),
        ('non_teaching', 'Non-Teaching Staff'),
    ], string='Teacher Type')
    is_own_driver = fields.Boolean(
        string='Driver Type (Own Driver)',
        help="Tick if this is an Own Driver (permanent payroll). Untick for Outside Driver (vendor/contract)."
    )
    
class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    resume_attachment = fields.Binary(string='Resume Attachment', attachment=True)
    resume_attachment_filename = fields.Char(string='Resume Filename')
    cover_letter = fields.Text(string='Cover Letter')
    
class HrApplicantInterview(models.Model):
    _name = 'hr.applicant.interview'
    _description = 'Interview Record'
    _order = 'interview_date desc, interview_time desc'

    application_id = fields.Many2one('hr.applicant', string='Application', required=True, ondelete='cascade')
    interview_date = fields.Date(string='Interview Date', required=True)
    interview_time = fields.Float(string='Interview Time', widget='float_time')
    interviewer_id = fields.Many2one('res.users', string='Interviewer')
    interview_type = fields.Selection([
        ('phone', 'Phone'),
        ('video', 'Video'),
        ('in_person', 'In-Person'),
    ], string='Interview Type', required=True, default='in_person')
    interview_notes = fields.Text(string='Interview Notes')