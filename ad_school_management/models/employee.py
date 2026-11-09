from odoo import models, fields, api
from odoo.tools.sql import column_exists


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    teacher_code = fields.Char(string='Teacher Code', copy=False)
    qualification = fields.Char(string='Qualification')
    specialization = fields.Char(string='Specialization')
    joining_date = fields.Date(string='Joining Date')
    class_teacher_for = fields.Many2one('school.class', string='Class Teacher For')
    teacher_id = fields.Many2one('school.teacher', string='Teacher Profile', copy=False)
    teacher_type = fields.Selection([
        ('teaching', 'Teaching Staff'),
        ('non_teaching', 'Non-Teaching Staff'),
    ], string='Teacher Type', help='Classification of role eg: teaching staff, non-teaching staff')
    is_own_driver = fields.Boolean(
        string='Driver Type (Own Driver)',
        help="Tick if this is an Own Driver (permanent payroll). Untick for Outside Driver (vendor/contract)."
    )
    meal_entitled = fields.Boolean(
        string='Meal Entitled', default=False,
        help='Staff entitled to a canteen meal (used by the Canteen Daily Planning count)',
    )
    # Teacher form fields shown on the Employee form. They read from / write to
    # the linked Teacher record (teacher_id); nothing is stored on the employee.
    # Writes go through school.teacher with the current user's access rights.
    school_class_teacher_for_text = fields.Char(
        string='Class Teacher For', related='teacher_id.class_teacher_for_text')
    school_class_ids = fields.Many2many(
        'school.class', string='Assigned Classes', related='teacher_id.class_ids', readonly=False)
    school_subject_ids = fields.Many2many(
        'school.subject', string='Assigned Subjects', related='teacher_id.subject_ids', readonly=False)
    school_timetable_line_ids = fields.One2many(
        'school.timetable.line', string='My Periods', related='teacher_id.timetable_line_ids')

    def _auto_init(self):
        # One-time copy: meal_entitled used to be stored only on school.teacher.
        # When the hr_employee column is created (first upgrade), copy the
        # existing teacher values to their employee so no data is lost.
        cr = self.env.cr
        new_column = not column_exists(cr, 'hr_employee', 'meal_entitled')
        res = super()._auto_init()
        if new_column and column_exists(cr, 'school_teacher', 'meal_entitled'):
            cr.execute("""
                UPDATE hr_employee e
                   SET meal_entitled = t.meal_entitled
                  FROM school_teacher t
                 WHERE t.employee_id = e.id
                   AND t.meal_entitled IS NOT NULL
            """)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        # New employees only: give them a Teacher Code when none is provided.
        for vals in vals_list:
            if not vals.get('teacher_code'):
                vals['teacher_code'] = self.env['ir.sequence'].next_by_code('school.teacher.code')
        employees = super().create(vals_list)
        employees._school_create_teacher_profile()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if vals.get('teacher_type') == 'teaching':
            self._school_create_teacher_profile()
        return res

    def _school_create_teacher_profile(self):
        """Create the linked school.teacher for teaching employees that have none.

        Skipped when the employee is being created/written by school.teacher's
        own create (through _inherits), so no second Teacher is created."""
        if self.env.context.get('school_teacher_creating'):
            return
        employees = self.filtered(lambda e: e.teacher_type == 'teaching' and not e.teacher_id)
        if not employees:
            return
        existing = self.env['school.teacher'].search([('employee_id', 'in', employees.ids)])
        employees -= existing.employee_id
        if employees:
            # employee_id is given, so _inherits links to this employee instead
            # of creating a new one; school.teacher.create sets teacher_id.
            self.env['school.teacher'].create([{'employee_id': emp.id} for emp in employees])
    
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
