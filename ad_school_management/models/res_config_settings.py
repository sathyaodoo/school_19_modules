from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Which board a company / branch runs. Branches set it (CBSE branch =
    # CBSE, State Board branch = State Board); the main school leaves it
    # empty = all boards. Used to show the right House Championship.
    school_board = fields.Selection(
        [('cbse', 'CBSE'), ('state', 'State Board')], string='School Board',
        help='The board this branch runs. Leave empty for the main school (all boards). '
             'The House Championship on the dashboard shows the boards of the companies '
             'selected in the company switcher.')

    library_fine_per_day = fields.Float(
        string='Library Fine per Day', default=5.0,
        help='Fine charged for each day a library book is returned after its due date.')

    @api.constrains('library_fine_per_day')
    def _check_library_fine_per_day(self):
        for company in self:
            if company.library_fine_per_day < 0:
                raise ValidationError(_("The late return fine cannot be negative."))

    # --- Library circulation rules ---------------------------------------
    library_loan_days = fields.Integer(string='Loan Period (days)', default=14)
    library_max_renewals = fields.Integer(string='Max Renewals', default=2)
    library_max_books = fields.Integer(string='Max Books per Member', default=3)
    library_reservation_hold_days = fields.Integer(string='Reservation Hold (days)', default=3)
    library_membership_required = fields.Boolean(string='Library Card Required to Borrow', default=False)

    # --- Early Warning System thresholds --------------------------------
    ews_marks_drop = fields.Integer(string='Sudden Fall in Marks (percentage points)', default=15)
    ews_decline_total = fields.Integer(string='Declining over 3 Exams (total percentage points)', default=15)
    ews_failures = fields.Integer(string='Repeated Failure (failed papers, last 2 exams)', default=2)
    ews_absence_days = fields.Integer(string='Frequent Absence (days in 30 days)', default=5)
    ews_monfri_absences = fields.Integer(string='Monday/Friday Absences (in 8 weeks)', default=3)
    ews_attendance_drop = fields.Integer(string='Attendance Drop (percentage points)', default=20)
    ews_incidents = fields.Integer(string='Disciplinary Incidents (in 60 days)', default=2)
    ews_red_score = fields.Integer(string='Immediate Intervention Score', default=5)

    @api.constrains('ews_marks_drop', 'ews_decline_total', 'ews_failures', 'ews_absence_days', 'ews_monfri_absences',
                    'ews_attendance_drop', 'ews_incidents', 'ews_red_score')
    def _check_ews(self):
        for company in self:
            if min(company.ews_marks_drop, company.ews_decline_total, company.ews_failures, company.ews_absence_days,
                   company.ews_monfri_absences, company.ews_attendance_drop, company.ews_incidents,
                   company.ews_red_score) < 0:
                raise ValidationError(_("Early warning thresholds cannot be negative (0 switches a check off)."))

    @api.constrains('library_loan_days', 'library_max_renewals', 'library_max_books',
                    'library_reservation_hold_days')
    def _check_library_rules(self):
        for company in self:
            if min(company.library_loan_days, company.library_max_renewals, company.library_max_books,
                   company.library_reservation_hold_days) < 0:
                raise ValidationError(_("Library settings cannot be negative."))

    # --- House Championship: points given automatically from Activities ---
    # (edited in Settings > School Management > House Championship)
    house_points_first = fields.Integer(string='First Place Points', default=10)
    house_points_second = fields.Integer(string='Second Place Points', default=7)
    house_points_third = fields.Integer(string='Third Place Points', default=5)
    house_points_participation = fields.Integer(
        string='Participation Points (per student)', default=1,
        help='Given to the house for every student taking part in an activity (Teamwork & Cooperation).')
    house_points_group_participation = fields.Integer(
        string='Group Event Participation Points (per house)', default=5,
        help='Given to every house taking part in a group (house) event (Teamwork & Cooperation).')

    @api.constrains('house_points_first', 'house_points_second', 'house_points_third',
                    'house_points_participation', 'house_points_group_participation')
    def _check_house_points(self):
        for company in self:
            values = [company.house_points_first, company.house_points_second, company.house_points_third,
                      company.house_points_participation, company.house_points_group_participation]
            if any(value < 0 for value in values):
                raise ValidationError(_("House points cannot be negative (use 0 to give no points)."))

    # --- Student Activity Score: points a STUDENT earns from activities ---
    # (edited in Settings > School Management > Student Activity Score)
    # Every activity a student takes part in earns the participation points;
    # a prize adds the First / Second / Third place points on top. The monthly
    # and total score of a student is the sum of these points.
    # No built-in values: every point is set by the school in Settings
    # (0 = no points until the school enters its own values).
    student_score_participation = fields.Integer(
        string='Participation Points (per activity)', default=0,
        help='Points a student earns for every school activity they take part in.')
    student_score_first = fields.Integer(string='First Place Bonus', default=0)
    student_score_second = fields.Integer(string='Second Place Bonus', default=0)
    student_score_third = fields.Integer(string='Third Place Bonus', default=0)

    @api.constrains('student_score_participation', 'student_score_first',
                    'student_score_second', 'student_score_third')
    def _check_student_score(self):
        for company in self:
            values = [company.student_score_participation, company.student_score_first,
                      company.student_score_second, company.student_score_third]
            if any(value < 0 for value in values):
                raise ValidationError(_("Student score points cannot be negative (use 0 to give no points)."))

    # --- Exam total: activity marks added by the teacher ----------------
    # Nothing is added automatically: the teacher adds activity marks for the
    # students they choose, in the exam's "Activity Marks" tab.
    exam_include_activity_score = fields.Boolean(
        string='Allow Activity Marks in Exam Total', default=False,
        help='When ticked, teachers pick a student and a subject in each exam (Activity Marks tab) '
             'and type the activity marks. Only the marks they add are counted in the Mark List.')
    exam_activity_score_max = fields.Integer(
        string='Maximum Activity Marks', default=0,
        help='Most activity marks one student can get in one exam, all subjects together. '
             '0 = no limit (a subject never goes above its max marks).')

    @api.constrains('exam_activity_score_max')
    def _check_exam_activity_score_max(self):
        for company in self:
            if company.exam_activity_score_max < 0:
                raise ValidationError(_("Maximum activity marks cannot be negative (0 = no limit)."))
            
    def _school_student_score_values(self):
        """Default student score points of this company (an activity can
        override them, see event.event._school_student_score_values)."""
        self.ensure_one()
        return {
            'participation': self.student_score_participation,
            'place': {
                'first': self.student_score_first,
                'second': self.student_score_second,
                'third': self.student_score_third,
            },
        }

    def _school_house_point_values(self):
        """Point values used for activities of this company."""
        self.ensure_one()
        return {
            'place': {
                'first': self.house_points_first,
                'second': self.house_points_second,
                'third': self.house_points_third,
            },
            'participation': self.house_points_participation,
            'group_participation': self.house_points_group_participation,
        }


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    library_fine_per_day = fields.Float(
        related='company_id.library_fine_per_day', readonly=False,
        string='Fine per Day')
    library_currency_id = fields.Many2one(
        related='company_id.currency_id', string='Library Currency', readonly=True)

    library_loan_days = fields.Integer(related='company_id.library_loan_days', readonly=False)
    library_max_renewals = fields.Integer(related='company_id.library_max_renewals', readonly=False)
    library_max_books = fields.Integer(related='company_id.library_max_books', readonly=False)
    library_reservation_hold_days = fields.Integer(related='company_id.library_reservation_hold_days',
                                                   readonly=False)
    library_membership_required = fields.Boolean(related='company_id.library_membership_required',
                                                 readonly=False)
    ews_marks_drop = fields.Integer(related='company_id.ews_marks_drop', readonly=False)
    ews_decline_total = fields.Integer(related='company_id.ews_decline_total', readonly=False)
    ews_failures = fields.Integer(related='company_id.ews_failures', readonly=False)
    ews_absence_days = fields.Integer(related='company_id.ews_absence_days', readonly=False)
    ews_monfri_absences = fields.Integer(related='company_id.ews_monfri_absences', readonly=False)
    ews_attendance_drop = fields.Integer(related='company_id.ews_attendance_drop', readonly=False)
    ews_incidents = fields.Integer(related='company_id.ews_incidents', readonly=False)
    ews_red_score = fields.Integer(related='company_id.ews_red_score', readonly=False)
    house_points_first = fields.Integer(related='company_id.house_points_first', readonly=False)
    house_points_second = fields.Integer(related='company_id.house_points_second', readonly=False)
    house_points_third = fields.Integer(related='company_id.house_points_third', readonly=False)
    house_points_participation = fields.Integer(
        related='company_id.house_points_participation', readonly=False)
    house_points_group_participation = fields.Integer(
        related='company_id.house_points_group_participation', readonly=False)

    student_score_participation = fields.Integer(
        related='company_id.student_score_participation', readonly=False)
    student_score_first = fields.Integer(related='company_id.student_score_first', readonly=False)
    student_score_second = fields.Integer(related='company_id.student_score_second', readonly=False)
    student_score_third = fields.Integer(related='company_id.student_score_third', readonly=False)

    exam_include_activity_score = fields.Boolean(
        related='company_id.exam_include_activity_score', readonly=False)
    exam_activity_score_max = fields.Integer(
        related='company_id.exam_activity_score_max', readonly=False)

    _HOUSE_POINT_SETTINGS = ('house_points_first', 'house_points_second', 'house_points_third',
                             'house_points_participation', 'house_points_group_participation')
    _STUDENT_SCORE_SETTINGS = ('student_score_participation', 'student_score_first',
                               'student_score_second', 'student_score_third')

    @api.model_create_multi
    def create(self, vals_list):
        """Saving Settings with changed point values applies them to every
        existing school activity / participant straight away. (The values are
        written to the company while the settings record is created, so the
        change is detected here, not in set_values.)"""
        company = self.env.company
        watched = self._HOUSE_POINT_SETTINGS + self._STUDENT_SCORE_SETTINGS
        before = {name: company[name] for name in watched}
        records = super().create(vals_list)
        for record in records:
            changed = {name for name in watched if record.company_id[name] != before[name]}
            if changed & set(self._HOUSE_POINT_SETTINGS):
                record._school_recalculate_activities()
            if changed & set(self._STUDENT_SCORE_SETTINGS):
                record._school_recalculate_student_scores()
        return records

    def _school_recalculate_activities(self):
        activities = self.env['event.event'].sudo().search([
            ('is_school_activity', '=', True),
            ('company_id', 'in', [self.company_id.id, False]),
        ])
        activities._school_sync_house_points()
        return activities

    def _school_recalculate_student_scores(self):
        """Rebuild the score of every participant of this company's school
        activities with the values now saved in Settings."""
        registrations = self.env['event.registration'].sudo().search([
            ('is_school_activity', '=', True),
            ('event_id.company_id', 'in', [self.company_id.id, False]),
        ])
        self.env.add_to_compute(registrations._fields['school_score'], registrations)
        self.env.flush_all()
        return registrations

    def action_recalculate_house_points(self):
        """'Recalculate Activity Points' button: apply the current values to
        every existing school activity (manual staff awards are not touched)."""
        self.execute()  # save the values shown on the screen first
        activities = self._school_recalculate_activities()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("House points recalculated"),
                'message': _("%s activity(ies) now use the current point values.", len(activities)),
            },
        }

    def action_recalculate_student_scores(self):
        """'Recalculate Student Scores' button: save the values shown on the
        screen, then rebuild the score of every participant."""
        self.execute()
        registrations = self._school_recalculate_student_scores()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Student scores recalculated"),
                'message': _("%s participation(s) now use the current point values.", len(registrations)),
            },
        }
