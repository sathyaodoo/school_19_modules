from odoo import models, fields, api, _

class SchoolAttendance(models.Model):
    _name = 'school.attendance'
    _description = 'Student Attendance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, student_id'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', required=True, tracking=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True)
    status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('leave', 'Leave'),
        ('late', 'Late')
    ], string='Status', required=True, default='present', tracking=True)

    _student_date_uniq = models.Constraint(
        'unique(student_id, date)', 'Attendance for this student on this date is already marked!'
    )
