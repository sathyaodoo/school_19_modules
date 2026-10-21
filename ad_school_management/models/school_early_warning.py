"""Early Warning System (BRS Part V-5).

The system looks at marks, attendance, participation, library use and
behaviour records and raises *signals*. Signals are grouped into an alert that
a teacher / counsellor must REVIEW: the system only suggests a level
(Requires attention / Immediate intervention); it never labels a child. The
student's status changes only when a person confirms it (mandatory safeguard).
"""
from collections import defaultdict
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

LEVELS = [
    ('green', 'Normal'),
    ('amber', 'Requires Attention'),
    ('red', 'Immediate Intervention'),
]
CATEGORIES = [
    ('academic', 'Academic'),
    ('attendance', 'Attendance'),
    ('engagement', 'Engagement'),
    ('behavioural', 'Behavioural'),
]
INDICATORS = [
    # academic
    ('marks_drop', 'Sudden fall in marks'),
    ('repeated_failure', 'Repeated failure'),
    ('declining', 'Declining performance across examinations'),
    # attendance
    ('frequent_absence', 'Frequent absence'),
    ('mon_fri_absence', 'Repeated Monday/Friday absence'),
    ('attendance_change', 'Sudden attendance-pattern change'),
    # engagement
    ('reduced_participation', 'Reduced participation'),
    ('no_participation', 'No activity participation'),
    ('reduced_library', 'Reduced library usage'),
    # behavioural
    ('repeated_incidents', 'Repeated disciplinary incidents'),
    ('behaviour_change', 'Sudden behavioural change'),
]
INDICATOR_CATEGORY = {
    'marks_drop': 'academic', 'repeated_failure': 'academic', 'declining': 'academic',
    'frequent_absence': 'attendance', 'mon_fri_absence': 'attendance', 'attendance_change': 'attendance',
    'reduced_participation': 'engagement', 'no_participation': 'engagement', 'reduced_library': 'engagement',
    'repeated_incidents': 'behavioural', 'behaviour_change': 'behavioural',
}


def _setting(env, name, default):
    company = env.company
    return company[name] if name in company._fields else default


# ======================================================================
# Behaviour incidents (source of the Behavioural Risk signals)
# ======================================================================
class SchoolStudentIncident(models.Model):
    _name = 'school.student.incident'
    _description = 'Student Behaviour Incident'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, index=True, tracking=True)
    class_id = fields.Many2one(related='student_id.class_id', string='Class', store=True)
    section_id = fields.Many2one(related='student_id.section_id', string='Section', store=True)
    category = fields.Selection([
        ('discipline', 'Disciplinary Incident'),
        ('bullying', 'Bullying / Conflict'),
        ('behaviour_change', 'Behaviour Change Observed'),
        ('wellbeing', 'Wellbeing Concern'),
        ('other', 'Other'),
    ], string='Type', required=True, default='discipline', tracking=True)
    severity = fields.Selection([('minor', 'Minor'), ('moderate', 'Moderate'), ('serious', 'Serious')],
                                string='Severity', required=True, default='minor', tracking=True)
    description = fields.Text(string='What happened', required=True)
    action_taken = fields.Text(string='Action Taken')
    reported_by = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user, readonly=True)

    @api.depends('student_id', 'date', 'category')
    def _compute_display_name(self):
        labels = dict(self._fields['category']._description_selection(self.env))
        for rec in self:
            rec.display_name = '%s – %s (%s)' % (rec.student_id.name or '', labels.get(rec.category, ''), rec.date or '')


# ======================================================================
# Alerts and signals
# ======================================================================
class SchoolEarlyWarning(models.Model):
    _name = 'school.early.warning'
    _description = 'Early Warning Alert'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'state_sequence, suggested_sequence desc, date desc, id desc'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False, default='/')
    student_id = fields.Many2one('school.student', string='Student', required=True, index=True, readonly=True)
    class_id = fields.Many2one(related='student_id.class_id', string='Class', store=True)
    section_id = fields.Many2one(related='student_id.section_id', string='Section', store=True)
    date = fields.Date(string='Detected On', default=fields.Date.context_today, readonly=True)
    last_scan_date = fields.Date(string='Last Checked', readonly=True)

    # --- what the SYSTEM suggests (never shown as the child's status) ---
    suggested_level = fields.Selection(LEVELS, string='Suggested Level', readonly=True, tracking=True,
                                       help='Suggested by the early warning rules. It is only a prompt for '
                                            'review: a teacher / counsellor decides the actual level.')
    suggested_sequence = fields.Integer(compute='_compute_sequences', store=True)
    score = fields.Integer(string='Signal Score', readonly=True)
    signal_ids = fields.One2many('school.early.warning.signal', 'alert_id', string='Signals', readonly=True)
    category_summary = fields.Char(string='Risk Areas', compute='_compute_category_summary', store=True)

    # --- what a PERSON decides (mandatory human review) ---
    reviewer_id = fields.Many2one('res.users', string='Assigned Reviewer', tracking=True)
    confirmed_level = fields.Selection(LEVELS, string='Confirmed Level', tracking=True,
                                       help='Set by the teacher / counsellor after reviewing the signals.')
    review_note = fields.Text(string='Review Notes')
    reviewed_by = fields.Many2one('res.users', string='Reviewed By', readonly=True)
    review_date = fields.Datetime(string='Reviewed On', readonly=True)
    intervention_ids = fields.Many2many('school.early.warning.intervention', string='Interventions')
    action_plan = fields.Text(string='Action Plan')
    follow_up_date = fields.Date(string='Follow-up Date', tracking=True)
    closing_note = fields.Text(string='Outcome')
    dismiss_reason = fields.Text(string='Reason for Dismissal')

    state = fields.Selection([
        ('to_review', 'To Review'),
        ('in_progress', 'Intervention in Progress'),
        ('closed', 'Closed'),
        ('dismissed', 'Dismissed'),
    ], string='Status', default='to_review', required=True, tracking=True, index=True)
    state_sequence = fields.Integer(compute='_compute_sequences', store=True)

    @api.depends('state', 'suggested_level')
    def _compute_sequences(self):
        order = {'to_review': 1, 'in_progress': 2, 'closed': 3, 'dismissed': 4}
        level = {'green': 0, 'amber': 1, 'red': 2}
        for rec in self:
            rec.state_sequence = order.get(rec.state, 9)
            rec.suggested_sequence = level.get(rec.suggested_level, 0)

    @api.depends('signal_ids.category')
    def _compute_category_summary(self):
        labels = dict(CATEGORIES)
        for rec in self:
            cats = [labels[c] for c, _l in CATEGORIES if c in rec.signal_ids.mapped('category')]
            rec.category_summary = ', '.join(cats)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.early.warning') or '/'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Human review workflow
    # ------------------------------------------------------------------
    def action_confirm_review(self):
        for rec in self:
            if not rec.confirmed_level:
                raise UserError(_("Choose the Confirmed Level after reviewing the signals."))
            if not (rec.review_note or '').strip():
                raise UserError(_("Write your Review Notes (what you checked and concluded)."))
            if rec.confirmed_level != 'green' and not (rec.intervention_ids or (rec.action_plan or '').strip()):
                raise UserError(_("Choose at least one intervention or write an action plan."))
            rec.write({
                'reviewed_by': self.env.uid,
                'review_date': fields.Datetime.now(),
                'state': 'closed' if rec.confirmed_level == 'green' else 'in_progress',
                'closing_note': rec.closing_note or (_("Reviewed: no concern.") if rec.confirmed_level == 'green' else False),
            })
            rec.activity_feedback(['mail.mail_activity_data_todo'],
                                  feedback=_("Reviewed: %s", dict(LEVELS)[rec.confirmed_level]))
            if rec.follow_up_date and rec.state == 'in_progress':
                rec.activity_schedule('mail.mail_activity_data_todo', date_deadline=rec.follow_up_date,
                                      summary=_("Early warning follow-up: %s", rec.student_id.name),
                                      user_id=(rec.reviewer_id or self.env.user).id)
            rec.student_id._compute_wellbeing_status()

    def action_close(self):
        for rec in self:
            if not (rec.closing_note or '').strip():
                raise UserError(_("Write the Outcome before closing."))
            rec.state = 'closed'
            rec.activity_unlink(['mail.mail_activity_data_todo'])

    def action_dismiss(self):
        for rec in self:
            if not (rec.dismiss_reason or '').strip():
                raise UserError(_("Write the Reason for Dismissal (e.g. absence explained by medical leave)."))
            rec.write({'state': 'dismissed', 'reviewed_by': self.env.uid, 'review_date': fields.Datetime.now()})
            rec.activity_unlink(['mail.mail_activity_data_todo'])

    def action_reopen(self):
        self.write({'state': 'to_review'})

    # ------------------------------------------------------------------
    # Detection engine
    # ------------------------------------------------------------------
    @api.model
    def _detect_signals(self, student, today=None):
        """Return the signals for one student: [{indicator, detail, weight}]."""
        today = today or fields.Date.context_today(self)
        env = self.env
        signals = []

        def add(indicator, detail, weight):
            signals.append({'indicator': indicator, 'category': INDICATOR_CATEGORY[indicator],
                            'detail': detail, 'weight': weight})

        # ---------------- Academic ----------------
        # Checked on the overall average AND on every subject, so a fall in
        # one subject (e.g. Maths 100 -> 80 -> 60) is not hidden by another
        # subject going up.
        results = env['school.exam.result'].sudo().search([('student_id', '=', student.id)])
        epoch = fields.Date.from_string('1900-01-01')

        def exam_date(rows):
            dates = [r.exam_subject_id.date for r in rows if r.exam_subject_id.date]
            return min(dates) if dates else epoch

        by_exam = defaultdict(list)
        for res in results:
            by_exam[res.exam_id].append(res)
        # exams in date order: (date, id, exam, average %, rows)
        exams = sorted(((exam_date(rows), exam.id, exam, sum(r.percentage for r in rows) / len(rows), rows)
                        for exam, rows in by_exam.items()), key=lambda e: (e[0], e[1]))
        # every subject's own series in date order: subject -> [(date, exam, %)]
        by_subject = defaultdict(list)
        for res in results:
            by_subject[res.subject_id].append((res.exam_subject_id.date or epoch, res.exam_id.id, res.exam_id, res.percentage))
        for series in by_subject.values():
            series.sort(key=lambda x: (x[0], x[1]))

        drop_limit = _setting(env, 'ews_marks_drop', 15)
        decline_limit = _setting(env, 'ews_decline_total', 15)

        # Sudden fall in marks: latest exam vs the previous one.
        if drop_limit:
            falls = []
            if len(exams) >= 2 and exams[-2][3] - exams[-1][3] >= drop_limit:
                falls.append(_("Average %(a).0f%% → %(b).0f%% (%(e1)s → %(e2)s)",
                               a=exams[-2][3], b=exams[-1][3], e1=exams[-2][2].name, e2=exams[-1][2].name))
            for subject, series in sorted(by_subject.items(), key=lambda kv: kv[0].name or ''):
                if len(series) >= 2 and series[-2][3] - series[-1][3] >= drop_limit:
                    falls.append(_("%(subject)s %(a).0f%% → %(b).0f%%", subject=subject.name,
                                   a=series[-2][3], b=series[-1][3]))
            if falls:
                add('marks_drop', _("Fell by %(n)s+ points since the previous exam: %(list)s.",
                                    n=drop_limit, list='; '.join(falls)), 2)

        # Declining performance: each of the last 3 exams lower than the one
        # before AND a meaningful total fall (100 -> 80 -> 60 yes, 100 -> 98 -> 96 no).
        if decline_limit:
            declines = []
            if len(exams) >= 3:
                a, b, c = exams[-3][3], exams[-2][3], exams[-1][3]
                if a > b > c and a - c >= decline_limit:
                    declines.append(_("Average %(a).0f%% → %(b).0f%% → %(c).0f%%", a=a, b=b, c=c))
            for subject, series in sorted(by_subject.items(), key=lambda kv: kv[0].name or ''):
                if len(series) >= 3:
                    a, b, c = series[-3][3], series[-2][3], series[-1][3]
                    if a > b > c and a - c >= decline_limit:
                        declines.append(_("%(subject)s %(a).0f%% → %(b).0f%% → %(c).0f%%",
                                          subject=subject.name, a=a, b=b, c=c))
            if declines:
                add('declining', _("Lower in each of the last three exams: %s.", '; '.join(declines)), 1)

        # Repeated failure: failed papers in the last two exams.
        fail_limit = _setting(env, 'ews_failures', 2)
        recent_fails = [r for e in exams[-2:] for r in e[4] if r.result_status == 'fail']
        if fail_limit and len(recent_fails) >= fail_limit:
            add('repeated_failure', _("Failed %(n)s paper(s) in the last two exams: %(subjects)s.",
                                      n=len(recent_fails),
                                      subjects=', '.join(sorted({r.subject_id.name for r in recent_fails}))), 2)

        # ---------------- Attendance ----------------
        Attendance = env['school.attendance'].sudo()
        att_domain = [('student_id', '=', student.id)]
        if 'session' in Attendance._fields:
            att_domain.append(('session', '=', 'morning'))
        att = Attendance.search(att_domain + [('date', '>=', today - timedelta(days=56)), ('date', '<=', today)])
        absent = att.filtered(lambda a: a.status == 'absent')
        last30 = absent.filtered(lambda a: a.date >= today - timedelta(days=30))
        absence_limit = _setting(env, 'ews_absence_days', 5)
        if absence_limit and len(last30) >= absence_limit:
            add('frequent_absence', _("Absent %s day(s) in the last 30 days.", len(last30)), 2)
        monfri = absent.filtered(lambda a: a.date.weekday() in (0, 4))
        monfri_limit = _setting(env, 'ews_monfri_absences', 3)
        if monfri_limit and len(monfri) >= monfri_limit and len(monfri) * 2 >= len(absent):
            add('mon_fri_absence', _("%(n)s of %(t)s absences in the last 8 weeks were on a Monday or Friday.",
                                     n=len(monfri), t=len(absent)), 1)
        recent = att.filtered(lambda a: a.date >= today - timedelta(days=14))
        before = att.filtered(lambda a: a.date < today - timedelta(days=14))
        if len(recent) >= 5 and len(before) >= 5:
            rate_recent = 100.0 * len(recent.filtered(lambda a: a.status == 'present')) / len(recent)
            rate_before = 100.0 * len(before.filtered(lambda a: a.status == 'present')) / len(before)
            if rate_before - rate_recent >= _setting(env, 'ews_attendance_drop', 20):
                add('attendance_change', _("Attendance dropped from %(b).0f%% (previous 6 weeks) to %(r).0f%% "
                                           "(last 2 weeks).", b=rate_before, r=rate_recent), 2)

        # ---------------- Engagement ----------------
        Reg = env['event.registration'].sudo()
        regs = Reg.search([('student_id', '=', student.id), ('state', '!=', 'cancel'),
                           ('event_id.is_school_activity', '=', True),
                           ('event_id.date_begin', '>=', fields.Datetime.to_datetime(today - timedelta(days=180)))])
        cur = regs.filtered(lambda r: r.event_id.date_begin.date() >= today - timedelta(days=90))
        prev = regs - cur
        if len(prev) >= 2 and len(cur) * 2 <= len(prev):
            add('reduced_participation', _("Took part in %(c)s activity(ies) in the last 3 months, %(p)s in the "
                                           "3 months before.", c=len(cur), p=len(prev)), 1)
        Event = env['event.event'].sudo()
        since = fields.Datetime.to_datetime(today - timedelta(days=120))
        ev_domain = [('is_school_activity', '=', True), ('date_begin', '>=', since),
                     ('date_begin', '<=', fields.Datetime.to_datetime(today))]
        if 'school_class_ids' in Event._fields and student.class_id:
            ev_domain += ['|', ('school_class_ids', '=', False), ('school_class_ids', 'in', student.class_id.ids)]
        offered = Event.search_count(ev_domain)
        took_part = regs.filtered(lambda r: r.event_id.date_begin >= since)
        if offered >= 2 and not took_part:
            add('no_participation', _("No participation in any of the %s activities open to the class in the "
                                      "last 4 months.", offered), 1)
        Issue = env['school.book.issue'].sudo()
        issues = Issue.search([('student_id', '=', student.id), ('state', '!=', 'draft'),
                               ('issue_date', '>=', today - timedelta(days=120))])
        lib_cur = issues.filtered(lambda i: i.issue_date >= today - timedelta(days=60))
        lib_prev = issues - lib_cur
        if len(lib_prev) >= 2 and not lib_cur:
            add('reduced_library', _("No library books borrowed in the last 2 months (borrowed %s in the 2 months "
                                     "before).", len(lib_prev)), 1)

        # ---------------- Behavioural ----------------
        Incident = env['school.student.incident'].sudo()
        incidents = Incident.search([('student_id', '=', student.id), ('date', '>=', today - timedelta(days=120))])
        disciplinary = incidents.filtered(lambda i: i.category in ('discipline', 'bullying')
                                          and i.date >= today - timedelta(days=60))
        incident_limit = _setting(env, 'ews_incidents', 2)
        serious = incidents.filtered(lambda i: i.severity == 'serious' and i.date >= today - timedelta(days=30))
        if (incident_limit and len(disciplinary) >= incident_limit) or serious:
            add('repeated_incidents', _("%(n)s disciplinary incident(s) in the last 60 days%(serious)s.",
                                        n=len(disciplinary),
                                        serious=_(", including a serious one") if serious else ''),
                3 if serious else 2)
        last30_inc = incidents.filtered(lambda i: i.date >= today - timedelta(days=30))
        earlier_inc = incidents - last30_inc
        observed = last30_inc.filtered(lambda i: i.category in ('behaviour_change', 'wellbeing'))
        if observed or (len(last30_inc) >= 2 and not earlier_inc):
            add('behaviour_change', _("%s behaviour / wellbeing observation(s) in the last 30 days.",
                                      len(observed) or len(last30_inc)), 2)
        return signals

    @api.model
    def _suggest_level(self, signals):
        if not signals:
            return 'green', 0
        score = sum(s['weight'] for s in signals)
        categories = {s['category'] for s in signals}
        serious = any(s['weight'] >= 3 for s in signals)
        if serious or score >= _setting(self.env, 'ews_red_score', 5) or len(categories) >= 3:
            return 'red', score
        return 'amber', score

    @api.model
    def _default_reviewer(self, student):
        """Who reviews: the class teacher, else a counsellor, else the
        principal, else a school administrator."""
        teacher = student.class_id.class_teacher_id
        if teacher.user_id and teacher.user_id.active:
            return teacher.user_id
        for xmlid in ('group_school_counsellor', 'group_school_principal', 'group_school_admin'):
            group = self.env.ref('ad_school_management.%s' % xmlid, raise_if_not_found=False)
            users = group.user_ids.filtered(lambda u: u.active and not u.share and u.id != 1) if group else False
            if users:
                return users.sorted('id')[:1]
        return self.env['res.users']

    @api.model
    def _scan_students(self, students=None):
        """Check students and create / update alerts for review.
        Returns (created, updated) alerts."""
        students = students if students is not None else self.env['school.student'].sudo().search([])
        today = fields.Date.context_today(self)
        Alert = self.sudo()
        created = updated = Alert.browse()
        counsellors = self.env.ref('ad_school_management.group_school_counsellor', raise_if_not_found=False)
        for student in students:
            signals = self._detect_signals(student, today)
            level, score = self._suggest_level(signals)
            alert = Alert.search([('student_id', '=', student.id), ('state', 'in', ('to_review', 'in_progress'))],
                                 limit=1)
            if level == 'green':
                if alert:
                    alert.last_scan_date = today
                continue
            lines = [(5, 0, 0)] + [(0, 0, dict(s, detected_on=today)) for s in signals]
            if alert:
                old_level = alert.suggested_level
                old_keys = set(alert.signal_ids.mapped('indicator'))
                alert.write({'signal_ids': lines, 'suggested_level': level, 'score': score,
                             'last_scan_date': today})
                new_keys = set(alert.signal_ids.mapped('indicator')) - old_keys
                if level == 'red' and old_level != 'red':
                    alert.message_post(body=_("New signals raised the suggested level to Immediate Intervention. "
                                              "Please review."), subtype_xmlid='mail.mt_note')
                    if alert.state != 'to_review':
                        alert.state = 'to_review'
                    alert._schedule_review_activity()
                elif new_keys:
                    alert.message_post(body=_("New signal(s): %s.", ', '.join(
                        dict(INDICATORS)[k] for k in new_keys)), subtype_xmlid='mail.mt_note')
                updated |= alert
                continue
            alert = Alert.create({
                'student_id': student.id, 'suggested_level': level, 'score': score,
                'signal_ids': lines[1:], 'reviewer_id': self._default_reviewer(student).id,
                'last_scan_date': today,
            })
            if counsellors:
                alert.message_subscribe(partner_ids=counsellors.user_ids.partner_id.ids)
            alert._schedule_review_activity()
            created |= alert
        return created, updated

    def _schedule_review_activity(self):
        for rec in self:
            if not rec.reviewer_id:
                continue
            if rec.activity_ids.filtered(lambda a: a.user_id == rec.reviewer_id):
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=fields.Date.context_today(rec) + timedelta(days=1 if rec.suggested_level == 'red' else 3),
                summary=_("Review early warning: %s", rec.student_id.name),
                note=Markup(_("The early warning rules suggest <b>%s</b>. Please review the signals and decide.")) %
                dict(LEVELS)[rec.suggested_level],
                user_id=rec.reviewer_id.id)

    @api.model
    def _cron_scan(self):
        self._scan_students()

    def action_run_scan(self):
        """'Run Early Warning Scan' button (list header).

        Odoo calls a list header button with the selected records: with no
        selection every student is checked; with alerts selected only the
        students of those alerts are re-checked."""
        students = self.student_id if self else None
        created, updated = self._scan_students(students)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': _("Early warning scan finished"),
                       'message': _("%(c)s new alert(s) to review, %(u)s open alert(s) updated.",
                                    c=len(created), u=len(updated)),
                       # refresh only the list, so this message stays visible
                       'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    @api.model
    def get_dashboard_stats(self):
        """Counts for the School Dashboard panel (only for staff who may see alerts)."""
        if not self.env['school.early.warning'].has_access('read'):
            return {'visible': False}
        Alert = self.env['school.early.warning']
        today = fields.Date.context_today(self)
        return {
            'visible': True,
            'to_review': Alert.search_count([('state', '=', 'to_review')]),
            'to_review_red': Alert.search_count([('state', '=', 'to_review'), ('suggested_level', '=', 'red')]),
            'red': Alert.search_count([('state', '=', 'in_progress'), ('confirmed_level', '=', 'red')]),
            'amber': Alert.search_count([('state', '=', 'in_progress'), ('confirmed_level', '=', 'amber')]),
            'follow_up_due': Alert.search_count([('state', '=', 'in_progress'), ('follow_up_date', '<=', today)]),
        }


class SchoolEarlyWarningSignal(models.Model):
    _name = 'school.early.warning.signal'
    _description = 'Early Warning Signal'
    _order = 'category, weight desc'

    alert_id = fields.Many2one('school.early.warning', required=True, ondelete='cascade', index=True)
    category = fields.Selection(CATEGORIES, string='Risk Area', required=True)
    indicator = fields.Selection(INDICATORS, string='Signal', required=True)
    detail = fields.Char(string='Evidence')
    weight = fields.Integer(string='Weight')
    detected_on = fields.Date(string='Detected On')


class SchoolEarlyWarningIntervention(models.Model):
    _name = 'school.early.warning.intervention'
    _description = 'Early Warning Intervention Type'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


# ======================================================================
# Student: status confirmed by a person (never by the system alone)
# ======================================================================
class SchoolStudentEarlyWarning(models.Model):
    _inherit = 'school.student'

    _EWS_GROUPS = ('ad_school_management.group_school_teacher,ad_school_management.group_school_counsellor,'
                   'ad_school_management.group_school_principal,ad_school_management.group_school_admin')

    wellbeing_status = fields.Selection(LEVELS, string='Wellbeing Status', compute='_compute_wellbeing_status',
                                        groups=_EWS_GROUPS,
                                        help='Confirmed by a teacher / counsellor after reviewing an early warning. '
                                             'The system alone never changes it.')
    early_warning_count = fields.Integer(string='Open Early Warnings', compute='_compute_wellbeing_status',
                                         groups=_EWS_GROUPS)
    incident_count = fields.Integer(string='Behaviour Incidents', compute='_compute_wellbeing_status',
                                    groups=_EWS_GROUPS)

    def _compute_wellbeing_status(self):
        Alert = self.env['school.early.warning'].sudo()
        Incident = self.env['school.student.incident'].sudo()
        for student in self:
            if not student.id:
                student.wellbeing_status = 'green'
                student.early_warning_count = student.incident_count = 0
                continue
            open_alerts = Alert.search([('student_id', '=', student.id), ('state', 'in', ('to_review', 'in_progress'))])
            confirmed = open_alerts.filtered(lambda a: a.state == 'in_progress' and a.confirmed_level)
            levels = confirmed.mapped('confirmed_level')
            student.wellbeing_status = 'red' if 'red' in levels else ('amber' if 'amber' in levels else 'green')
            student.early_warning_count = len(open_alerts)
            student.incident_count = Incident.search_count([('student_id', '=', student.id)])

    def action_view_early_warnings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Early Warnings – %s', self.name),
            'res_model': 'school.early.warning', 'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
        }

    def action_view_incidents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Behaviour Incidents – %s', self.name),
            'res_model': 'school.student.incident', 'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)], 'context': {'default_student_id': self.id},
        }

    def action_check_early_warning(self):
        """Kept for compatibility (the "Check Early Warning" header button was
        removed: use the Early Warnings smart button or Run Early Warning Scan).
        Runs the early-warning rules for this student only."""
        created, updated = self.env['school.early.warning']._scan_students(self)
        alert = created or updated
        if not alert:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'type': 'info', 'title': _("No early warning signals"),
                               'message': _("No signals were found for %s.", self.name)}}
        return {'type': 'ir.actions.act_window', 'res_model': 'school.early.warning', 'res_id': alert[:1].id,
                'view_mode': 'form', 'views': [(False, 'form')]}