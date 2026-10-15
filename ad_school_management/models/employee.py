from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    teacher_code = fields.Char(string='Teacher Code', copy=False)
    qualification = fields.Char(string='Qualification')
    specialization = fields.Char(string='Specialization')
    joining_date = fields.Date(string='Joining Date')
    class_teacher_for = fields.Many2one('school.class', string='Class Teacher For')
    teacher_id = fields.Many2one('school.teacher', string='Teacher Profile')
    teacher_type = fields.Selection([
        ('teaching', 'Teaching Staff'),
        ('non_teaching', 'Non-Teaching Staff'),
    ], string='Teacher Type')
    ], string='Teacher Type', help='Classification of role eg: teaching staff, non-teaching staff')
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
    teacher_type = fields.Selection([('teaching', 'Teaching Staff'),('non_teaching', 'Non-Teaching Staff'),],string='Teacher Type',help='Classification of role eg: teaching staff, non-teaching staff',)
    driver_type = fields.Boolean(string='Driver Type',help='Own Driver or Outside Driver',)
    driver_type = fields.Boolean(
        string='Driver Type',
        help='Own Driver or Outside Driver'
    )
    meal_entitled = fields.Boolean(
        string='Meal Entitled', default=False,
        string='Meal Entitled',
        default=False,
        help='Staff entitled to a canteen meal (used by the Canteen Daily Planning count)',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('teacher_code'):
                vals['teacher_code'] = self.env['ir.sequence'].next_by_code('school.teacher.code')
        return super().create(vals_list)

    @api.onchange('user_id')
    def _onchange_user_id_autofill_from_user(self):
        for employee in self:
            if not employee.user_id:
                continue
            user = employee.user_id
            partner = user.partner_id

            if not employee.name:
                employee.name = user.name
            if not employee.work_email:
                employee.work_email = partner.email or user.login
            if not employee.work_phone:
                employee.work_phone = partner.phone or partner.mobile


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
