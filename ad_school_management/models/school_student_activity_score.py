from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class SchoolStudentActivityScore(models.Model):
    """Monthly activity score of a student (read-only report).

    One row per student and month in which the student took part in at least
    one school activity. The score is the sum of the points of that month's
    activities (participation + prize points). Nothing is typed in here: the
    points come from event.registration.school_score, which follows
    Settings > School Management > Student Activity Score (or the activity's
    own custom points).
    """
    _name = 'school.student.activity.score'
    _description = 'Student Monthly Activity Score'
    _auto = False
    _order = 'month desc, total_score desc, student_id'
    _rec_name = 'student_id'

    student_id = fields.Many2one('school.student', string='Student', readonly=True)
    admission_no = fields.Char(related='student_id.admission_no', string='Admission No')
    class_id = fields.Many2one('school.class', string='Class', readonly=True)
    section_id = fields.Many2one('school.section', string='Section', readonly=True)
    house_id = fields.Many2one('school.house', string='Group (House)', readonly=True)
    month = fields.Date(string='Month', readonly=True)
    month_label = fields.Char(string='Month Name', readonly=True)
    activity_count = fields.Integer(string='Activities', readonly=True)
    prize_count = fields.Integer(string='Prizes', readonly=True)
    participation_points = fields.Integer(string='Participation Points', readonly=True)
    prize_points = fields.Integer(string='Prize Points', readonly=True)
    total_score = fields.Integer(string='Total Score', readonly=True)

    @property
    def _table_query(self):
        return """
            SELECT
                MIN(r.id) AS id,
                r.student_id AS student_id,
                s.class_id AS class_id,
                s.section_id AS section_id,
                s.house_id AS house_id,
                DATE_TRUNC('month', r.school_activity_date::timestamp)::date AS month,
                TO_CHAR(DATE_TRUNC('month', r.school_activity_date::timestamp), 'Mon YYYY') AS month_label,
                COUNT(r.id) AS activity_count,
                COUNT(r.school_position) AS prize_count,
                SUM(r.school_participation_points) AS participation_points,
                SUM(r.school_prize_points) AS prize_points,
                SUM(r.school_score) AS total_score
            FROM event_registration r
            JOIN school_student s ON s.id = r.student_id
            WHERE r.is_school_activity
              AND r.state != 'cancel'
              AND r.student_id IS NOT NULL
              AND r.school_activity_date IS NOT NULL
            GROUP BY r.student_id, s.class_id, s.section_id, s.house_id,
                     DATE_TRUNC('month', r.school_activity_date::timestamp)
        """


class SchoolStudentScore(models.Model):
    """Score of a student on the student record: this month and in total."""
    _inherit = 'school.student'

    _SCORE_GROUPS = ('ad_school_management.group_school_admin,'
                     'ad_school_management.group_school_principal,'
                     'ad_school_management.group_school_teacher')

    activity_score_ids = fields.One2many(
        'school.student.activity.score', 'student_id', string='Monthly Activity Score',
        groups=_SCORE_GROUPS)
    activity_month_score = fields.Integer(
        string="This Month's Score", compute='_compute_activity_scores', groups=_SCORE_GROUPS)
    activity_total_score = fields.Integer(
        string='Total Activity Score', compute='_compute_activity_scores', groups=_SCORE_GROUPS)

    @api.depends('activity_registration_ids.school_score',
                 'activity_registration_ids.school_activity_date',
                 'activity_registration_ids.state')
    def _compute_activity_scores(self):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        next_month = month_start + relativedelta(months=1)
        for student in self:
            regs = student.activity_registration_ids
            student.activity_total_score = sum(regs.mapped('school_score'))
            this_month = regs.filtered(
                lambda r: r.school_activity_date and month_start <= r.school_activity_date < next_month)
            student.activity_month_score = sum(this_month.mapped('school_score'))

    def action_view_student_scores(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Activity Score: %s', self.name),
            'res_model': 'school.student.activity.score',
            'view_mode': 'list,pivot,graph',
            'domain': [('student_id', '=', self.id)],
            'context': {'create': False},
        }