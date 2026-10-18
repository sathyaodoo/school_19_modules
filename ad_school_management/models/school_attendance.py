from odoo import models, fields, api, _

# Attendance is taken ONCE a day (in the morning).
# The 'session' field is kept only so that old records from the time when
# attendance was taken twice a day stay in the database: every new record is
# 'morning' (= the day's attendance) and old 'afternoon' records are hidden
# everywhere (menus, dashboard, portal).
SESSIONS = [
    ('morning', 'Morning'),
    ('afternoon', 'Afternoon (old, no longer used)'),
]
STATUSES = [
    ('present', 'Present'),
    ('absent', 'Absent'),
]
DAILY_DOMAIN = [('session', '=', 'morning')]


class SchoolAttendance(models.Model):
    """Student attendance: one record per student per day, Present or Absent."""
    _name = 'school.attendance'
    _description = 'Student Attendance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, student_id'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    session = fields.Selection(SESSIONS, string='Session', required=True, default='morning', index=True,
                               readonly=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', required=True, tracking=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True)
    status = fields.Selection(STATUSES, string='Status', required=True, default='present', tracking=True)

    _student_date_session_uniq = models.Constraint(
        'unique(student_id, date, session)',
        'Attendance for this student is already marked on this date!'
    )

    @api.depends('student_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s – %s' % (rec.student_id.name or '', rec.date or '')

    @api.model
    def _get_daily_summary(self, student, days=15):
        """For the portal: the student's attendance of the last `days` days,
        one row per day, newest first."""
        records = self.sudo().search(
            [('student_id', '=', student.id)] + DAILY_DOMAIN, order='date desc', limit=days)
        return [{
            'date': rec.date,
            'class_id': rec.class_id,
            'section_id': rec.section_id,
            'status': rec.status,
        } for rec in records]
