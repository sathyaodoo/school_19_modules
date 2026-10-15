from odoo import models, fields, api, _

SESSIONS = [
    ('morning', 'Morning'),
    ('afternoon', 'Afternoon'),
]
STATUSES = [
    ('present', 'Present'),
    ('absent', 'Absent'),
    ('leave', 'Leave'),
    ('late', 'Late'),
]


class SchoolAttendance(models.Model):
    """Student attendance, marked separately for the Morning and the
    Afternoon session: one record per student, per date, per session."""
    _name = 'school.attendance'
    _description = 'Student Attendance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    # 'session desc' puts Morning before Afternoon ('m' > 'a').
    _order = 'date desc, session desc, student_id'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    session = fields.Selection(SESSIONS, string='Session', required=True, default='morning',
                               tracking=True, index=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', required=True, tracking=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True)
    status = fields.Selection(STATUSES, string='Status', required=True, default='present', tracking=True)

    _student_date_session_uniq = models.Constraint(
        'unique(student_id, date, session)',
        'Attendance for this student is already marked for this session on this date!'
    )

    @api.depends('student_id', 'date', 'session')
    def _compute_display_name(self):
        sessions = dict(SESSIONS)
        for rec in self:
            rec.display_name = '%s – %s (%s)' % (
                rec.student_id.name or '', rec.date or '', sessions.get(rec.session, ''))

    @api.model
    def _default_session_now(self):
        """Morning before 12:00 (user's time zone), Afternoon from 12:00."""
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        return 'morning' if now.hour < 12 else 'afternoon'

    @api.model
    def _get_daily_summary(self, student, days=15):
        """For the portal: one row per date with the Morning and Afternoon
        status side by side, newest first."""
        records = self.sudo().search([('student_id', '=', student.id)], order='date desc, session')
        by_date = {}
        for rec in records:
            row = by_date.setdefault(rec.date, {
                'date': rec.date, 'class_id': rec.class_id, 'section_id': rec.section_id,
                'morning': False, 'afternoon': False,
            })
            row[rec.session] = rec.status
            if len(by_date) > days:
                by_date.pop(rec.date)
                break
        return list(by_date.values())