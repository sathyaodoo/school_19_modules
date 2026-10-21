from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

STRENGTH_PCT = 75.0          # subject average at or above = strength
SUPPORT_PCT = 50.0           # subject average below = needs support
FALL_POINTS = 15.0           # fall since the previous exam that counts as a gap
LOW_ATTENDANCE = 85.0        # attendance % below = area requiring support

LEVELS = [('1', 'Beginning'), ('2', 'Developing'), ('3', 'Proficient'), ('4', 'Advanced')]
COMPETENCY_CATEGORIES = [
    ('learning_outcome', 'Learning Outcome'),
    ('competency', 'Competency'),
    ('skill', 'Life Skill'),
    ('communication', 'Communication'),
    ('creativity', 'Creativity'),
]
RECORD_KINDS = [
    ('competition', 'Competition'),
    ('project', 'Project'),
    ('skill', 'Skill Acquired'),
    ('certification', 'Certification'),
    ('achievement', 'Achievement / Award'),
    ('leadership', 'Leadership Role'),
    ('community_service', 'Community Service'),
    ('environmental', 'Environmental Activity'),
    ('volunteering', 'Volunteering'),
    ('service_achievement', 'Service Achievement'),
]
AREAS = [('sports', 'Sports'), ('arts', 'Arts'), ('cultural', 'Cultural'), ('academic', 'Academic'),
         ('technology', 'Technology'), ('social', 'Social'), ('other', 'Other')]
BEHAVIOUR_RATINGS = [('4', 'Excellent'), ('3', 'Good'), ('2', 'Satisfactory'), ('1', 'Needs Improvement')]
REVIEW_PERIODS = [('q1', 'Quarter 1 (Q1)'), ('q2', 'Quarter 2 (Q2)'), ('q3', 'Quarter 3 (Q3)'),
                  ('q4', 'Quarter 4 (Q4)'), ('h1', 'First Half-Yearly (H1)'), ('h2', 'Second Half-Yearly (H2)')]
RECORD_LEVELS = [('class', 'Class'), ('school', 'School'), ('inter_school', 'Inter-School'), ('district', 'District'),
                 ('state', 'State'), ('national', 'National'), ('international', 'International')]


VIEWER_GROUPS = ('ad_school_management.group_school_teacher', 'ad_school_management.group_school_counsellor',
                 'ad_school_management.group_school_principal', 'ad_school_management.group_school_admin')


def _check_360_viewer(env):
    """The 360 profile (learning gaps, support needs, wellbeing) is for
    teachers, counsellors, the principal and school admins only."""
    if not (env.is_superuser() or any(env.user.has_group(g) for g in VIEWER_GROUPS)):
        raise AccessError(_("Only teachers, counsellors, the Principal and School Admins can see the 360° profile."))


def _year_of(env, day):
    if not day:
        return env['school.academic.year']
    return env['school.academic.year'].sudo().search(
        [('date_start', '<=', day), ('date_end', '>=', day)], limit=1)


# ======================================================================
# Competency framework and assessments
# ======================================================================
class SchoolCompetency(models.Model):
    _name = 'school.competency'
    _description = 'Learning Outcome / Competency'
    _order = 'category, sequence, name'

    name = fields.Char(string='Learning Outcome / Competency', required=True, translate=True,
                       help='e.g. "Solves word problems with fractions", "Critical thinking", "Public speaking"')
    code = fields.Char(string='Code', help='e.g. the CBSE learning-outcome code')
    category = fields.Selection(COMPETENCY_CATEGORIES, string='Category', required=True, default='learning_outcome')
    subject_id = fields.Many2one('school.subject', string='Subject', help='For subject learning outcomes.')
    class_ids = fields.Many2many('school.class', string='Classes', help='Leave empty for all classes.')
    description = fields.Text(string='Description / Descriptors')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class SchoolStudentCompetency(models.Model):
    _name = 'school.student.competency'
    _description = 'Student Competency Assessment'
    _order = 'date desc, id desc'

    student_id = fields.Many2one('school.student', string='Student', required=True, index=True, ondelete='cascade')
    class_id = fields.Many2one(related='student_id.class_id', string='Class', store=True)
    competency_id = fields.Many2one('school.competency', string='Learning Outcome / Competency', required=True,
                                    ondelete='restrict')
    category = fields.Selection(related='competency_id.category', store=True)
    subject_id = fields.Many2one(related='competency_id.subject_id', store=True)
    level = fields.Selection(LEVELS, string='Level', required=True, default='2')
    date = fields.Date(string='Assessed On', required=True, default=fields.Date.context_today)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year',
                                       compute='_compute_academic_year', store=True)
    evidence = fields.Text(string='Evidence / Observation',
                           help='What the student did that shows this level (task, project, observation).')
    assessed_by = fields.Many2one('res.users', string='Assessed By', default=lambda self: self.env.user, readonly=True)

    @api.depends('date')
    def _compute_academic_year(self):
        for rec in self:
            rec.academic_year_id = _year_of(self.env, rec.date)


# ======================================================================
# Behaviour and participation (reviewed every quarter / half-year)
# ======================================================================
class SchoolStudentBehaviour(models.Model):
    """One review (period + ratings + teacher observations) can cover many
    students, e.g. a whole group or class. The student's self-reflection and
    the parent's feedback are personal, so they live on one line per student
    (school.student.behaviour.feedback)."""
    _name = 'school.student.behaviour'
    _description = 'Student Behaviour & Participation Review'
    _order = 'academic_year_id desc, period, id desc'

    student_ids = fields.Many2many(
        'school.student', 'school_student_behaviour_student_rel', 'behaviour_id', 'student_id',
        string='Students', required=True,
        help='All the students this review applies to. They can belong to different classes.')
    class_ids = fields.Many2many(
        'school.class', 'school_student_behaviour_class_rel', 'behaviour_id', 'class_id',
        string='Classes', compute='_compute_class_ids', store=True,
        help="Filled in automatically from the students' classes.")
    period = fields.Selection(REVIEW_PERIODS, string='Review Period', required=True, default='q1',
                              help='Quarterly (Q1-Q4) or half-yearly (H1-H2) review.')
    period_type = fields.Selection([('quarterly', 'Quarterly'), ('half_yearly', 'Half-Yearly')],
                                   string='Frequency', compute='_compute_period_type', store=True)
    date = fields.Date(string='Reviewed On', required=True, default=fields.Date.context_today)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year',
                                       compute='_compute_academic_year', store=True, index=True)
    # the six BRS items
    behaviour = fields.Selection(BEHAVIOUR_RATINGS, string='Behaviour', required=True, default='3')
    discipline = fields.Selection(BEHAVIOUR_RATINGS, string='Discipline', required=True, default='3')
    participation = fields.Selection(BEHAVIOUR_RATINGS, string='Participation', required=True, default='3')
    teacher_observation = fields.Text(string='Teacher Observations')
    feedback_ids = fields.One2many('school.student.behaviour.feedback', 'review_id',
                                   string='Student Self-Reflection & Parent Feedback')
    average_rating = fields.Float(string='Average (out of 4)', compute='_compute_average', store=True, digits=(3, 1))
    reviewed_by = fields.Many2one('res.users', string='Reviewed By', default=lambda self: self.env.user,
                                  readonly=True)
    portal_published = fields.Boolean(
        string='Show in Portal', default=True,
        help='When ticked, the students and their parents/guardians can see this review in their portal. '
             'Untick to keep a draft review visible to staff only.')

    # --- one feedback row for EVERY student of the review ------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_feedback_lines()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'student_ids' in vals:
            self._sync_feedback_lines()
        return res

    def _sync_feedback_lines(self):
        """Keep exactly one feedback row per student of the review: add the
        missing ones, drop the rows of students taken off the review."""
        Feedback = self.env['school.student.behaviour.feedback']
        for rec in self:
            stale = rec.feedback_ids.filtered(lambda f: f.student_id not in rec.student_ids)
            stale.unlink()
            missing = rec.student_ids - (rec.feedback_ids - stale).student_id
            if missing:
                Feedback.create([{'review_id': rec.id, 'student_id': s.id} for s in missing])

    @api.depends('student_ids.class_id')
    def _compute_class_ids(self):
        for rec in self:
            rec.class_ids = rec.student_ids.class_id

    @api.depends('period')
    def _compute_period_type(self):
        for rec in self:
            rec.period_type = 'half_yearly' if rec.period in ('h1', 'h2') else 'quarterly'

    @api.depends('date')
    def _compute_academic_year(self):
        for rec in self:
            rec.academic_year_id = _year_of(self.env, rec.date)

    @api.depends('behaviour', 'discipline', 'participation')
    def _compute_average(self):
        for rec in self:
            vals = [int(v) for v in (rec.behaviour, rec.discipline, rec.participation) if v]
            rec.average_rating = sum(vals) / len(vals) if vals else 0.0

    @api.constrains('student_ids', 'period', 'academic_year_id')
    def _check_one_review_per_period(self):
        """A student can have only one review per period in an academic year
        (replaces the old SQL unique(student_id, academic_year_id, period))."""
        for rec in self:
            if not rec.student_ids:
                continue
            clash = self.search([('id', '!=', rec.id), ('period', '=', rec.period),
                                 ('academic_year_id', '=', rec.academic_year_id.id),
                                 ('student_ids', 'in', rec.student_ids.ids)], limit=1)
            if clash:
                names = ', '.join((clash.student_ids & rec.student_ids).mapped('name'))
                raise ValidationError(_(
                    "Already reviewed for this period in this academic year: %s.", names))

    @api.depends('student_ids', 'period', 'academic_year_id')
    def _compute_display_name(self):
        labels = dict(REVIEW_PERIODS)
        for rec in self:
            names = rec.student_ids.mapped('name')
            who = ', '.join(names[:3]) + (_(" +%s more", len(names) - 3) if len(names) > 3 else '')
            rec.display_name = ' - '.join(filter(None, [who, labels.get(rec.period), rec.academic_year_id.name]))

    @api.model
    def _portal_save_feedback(self, review, student, partner, kind, text):
        """Save the student's reflection or the parent's feedback from the portal.

        Called by the portal controller (sudo). Only these two fields of the
        student's OWN feedback line can ever be changed from the portal; the
        ratings and the teacher observations are read-only there.
        """
        review.ensure_one()
        if not review.portal_published:
            raise AccessError(_("This review is not available in the portal."))
        if student not in review.student_ids:
            raise AccessError(_("This review does not cover this student."))
        text = (text or '').strip()[:2000]
        if kind == 'student':
            if student.partner_id != partner:
                raise AccessError(_("Only the student can write the self-reflection."))
            field = 'self_reflection'
        elif kind == 'parent':
            if partner not in student.parent_ids.partner_id:
                raise AccessError(_("Only a parent / guardian of this student can write the feedback."))
            field = 'parent_feedback'
        else:
            raise ValidationError(_("Unknown feedback type."))
        Feedback = self.env['school.student.behaviour.feedback'].sudo()
        line = Feedback.search([('review_id', '=', review.id), ('student_id', '=', student.id)], limit=1)
        if line:
            line.write({field: text})
        else:
            Feedback.create({'review_id': review.id, 'student_id': student.id, field: text})
        return True


class SchoolStudentBehaviourFeedback(models.Model):
    _name = 'school.student.behaviour.feedback'
    _description = 'Behaviour Review - Student Self-Reflection & Parent Feedback'
    _order = 'review_id, student_id'

    review_id = fields.Many2one('school.student.behaviour', string='Review', required=True,
                                ondelete='cascade', index=True)
    student_id = fields.Many2one('school.student', string='Student', required=True,
                                 ondelete='cascade', index=True)
    self_reflection = fields.Text(string='Student Self-Reflection',
                                  help="The student's own words about how the period went.")
    parent_feedback = fields.Text(string='Parent Feedback')

    _review_student_uniq = models.Constraint(
        'unique(review_id, student_id)', 'This student already has a feedback line on this review.')

    @api.constrains('review_id', 'student_id')
    def _check_student_in_review(self):
        for rec in self:
            if rec.student_id not in rec.review_id.student_ids:
                raise ValidationError(_("%s is not one of the students of this review.", rec.student_id.name))


# ======================================================================
# Clubs
# ======================================================================
class SchoolClub(models.Model):
    _name = 'school.club'
    _description = 'Student Club'
    _order = 'name'

    name = fields.Char(string='Club', required=True)
    club_type = fields.Selection([('academic', 'Academic'), ('sports', 'Sports'), ('arts', 'Arts'),
                                  ('cultural', 'Cultural'), ('eco', 'Eco / Environment'), ('service', 'Service'),
                                  ('technology', 'Technology'), ('literary', 'Literary / Debate'),
                                  ('other', 'Other')], string='Type', required=True, default='academic')
    teacher_id = fields.Many2one('school.teacher', string='Teacher in Charge')
    description = fields.Text()
    membership_ids = fields.One2many('school.club.membership', 'club_id', string='Members')
    member_count = fields.Integer(compute='_compute_member_count', string='Members Count')
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This club already exists!')

    def _compute_member_count(self):
        for club in self:
            club.member_count = len(club.membership_ids.filtered('is_current'))


class SchoolClubMembership(models.Model):
    _name = 'school.club.membership'
    _description = 'Club Membership'
    _order = 'date_start desc, id desc'

    club_id = fields.Many2one('school.club', string='Club', required=True, ondelete='cascade', index=True)
    club_type = fields.Selection(related='club_id.club_type', store=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, ondelete='cascade', index=True)
    class_id = fields.Many2one(related='student_id.class_id', string='Class', store=True)
    role = fields.Selection([('member', 'Member'), ('secretary', 'Secretary'), ('vice_president', 'Vice-President'),
                             ('president', 'President'), ('captain', 'Captain')], string='Role',
                            required=True, default='member')
    date_start = fields.Date(string='Joined On', required=True, default=fields.Date.context_today)
    date_end = fields.Date(string='Left On')
    is_current = fields.Boolean(compute='_compute_is_current', string='Current Member')

    def _compute_is_current(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_current = not rec.date_end or rec.date_end >= today

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("'Left On' cannot be before 'Joined On'."))


# ======================================================================
# Development records (projects, skills, certifications, achievements,
# competitions, leadership, community service, environment, volunteering)
# ======================================================================
class SchoolStudentRecord(models.Model):
    _name = 'school.student.record'
    _description = 'Student Development Record'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Title', required=True,
                       help='e.g. "Science Exhibition – Water Purifier Model", "Beach clean-up drive"')
    # One record can cover many students, from many classes (e.g. a group
    # project, a competition team, a community-service drive).
    student_ids = fields.Many2many(
        'school.student', 'school_student_record_student_rel', 'record_id', 'student_id',
        string='Students', required=True,
        help='All the students who took part. They can belong to different classes.')
    class_ids = fields.Many2many(
        'school.class', 'school_student_record_class_rel', 'record_id', 'class_id',
        string='Classes', compute='_compute_class_ids', store=True,
        help="Filled in automatically from the students' classes.")
    kind = fields.Selection(RECORD_KINDS, string='Record Type', required=True, default='achievement', tracking=True)
    area = fields.Selection(AREAS, string='Area')
    level = fields.Selection(RECORD_LEVELS, string='Level', default='school')
    result = fields.Char(string='Result / Position', help='e.g. "1st place", "Gold", "Grade A", "Completed"')
    hours = fields.Float(string='Hours', help='Hours of service / volunteering.')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year',
                                       compute='_compute_academic_year', store=True)
    description = fields.Text(string='Description / What the student did')
    evidence = fields.Binary(string='Certificate / Evidence', attachment=True)
    evidence_filename = fields.Char()
    recorded_by = fields.Many2one('res.users', string='Recorded By', default=lambda self: self.env.user, readonly=True)

    @api.depends('date')
    def _compute_academic_year(self):
        for rec in self:
            rec.academic_year_id = _year_of(self.env, rec.date)

    @api.depends('student_ids.class_id')
    def _compute_class_ids(self):
        for rec in self:
            rec.class_ids = rec.student_ids.class_id

    @api.constrains('hours')
    def _check_hours(self):
        if any(rec.hours < 0 for rec in self):
            raise ValidationError(_("Hours cannot be negative."))


# ======================================================================
# The 360° profile
# ======================================================================
class SchoolStudent360(models.Model):
    _inherit = 'school.student'

    # The full 360° profile shown in the student record ("360° Profile" tab)
    profile_360_html = fields.Html(
        string='360° Profile', compute='_compute_profile_360_html', sanitize=False,
        groups='ad_school_management.group_school_teacher,ad_school_management.group_school_counsellor,'
               'ad_school_management.group_school_principal,ad_school_management.group_school_admin')
    development_record_ids = fields.Many2many(
        'school.student.record', 'school_student_record_student_rel', 'student_id', 'record_id',
        string='Development Records')
    competency_ids = fields.One2many('school.student.competency', 'student_id', string='Competency Assessments')
    club_membership_ids = fields.One2many('school.club.membership', 'student_id', string='Clubs')
    behaviour_review_ids = fields.Many2many(
        'school.student.behaviour', 'school_student_behaviour_student_rel', 'student_id', 'behaviour_id',
        string='Behaviour & Participation Reviews')

    def _compute_profile_360_html(self):
        year = _year_of(self.env, fields.Date.context_today(self))
        QWeb = self.env['ir.qweb']
        for student in self:
            if not student.id:
                student.profile_360_html = False
                continue
            profile = student.sudo()._get_360_profile(year)
            student.profile_360_html = QWeb._render('ad_school_management.student_360_profile_body',
                                                    {'p': profile, 'year_name': year.name if year else ''})

    def action_open_360(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'school_student_360',
                'name': _('360° Profile – %s', self.name), 'params': {'student_id': self.id}}

    def action_print_360(self):
        return self.env.ref('ad_school_management.action_report_student_360').report_action(self)

    def _report_360_values(self):
        """Data for the printed 360° profile (current academic year)."""
        self.ensure_one()
        _check_360_viewer(self.env)
        year = _year_of(self.env, fields.Date.context_today(self))
        data = self.sudo()._get_360_profile(year)
        data['year_name'] = year.name if year else ''
        return data

    @api.model
    def get_student_360(self, student_id, year_id=False):
        """Data for the Student 360° screen. The user must be allowed to read
        the student (teachers: their own classes only)."""
        _check_360_viewer(self.env)
        student = self.browse(student_id).exists()
        if not student:
            return {}
        student.check_access('read')
        year = self.env['school.academic.year'].sudo().browse(year_id) if year_id else \
            _year_of(self.env, fields.Date.context_today(self))
        years = [{'id': y.id, 'name': y.name}
                 for y in self.env['school.academic.year'].sudo().search([], order='date_start desc')]
        data = student.sudo()._get_360_profile(year)
        data['years'] = years
        data['year'] = {'id': year.id, 'name': year.name} if year else False
        return data

    @api.model
    def search_360_students(self, term=''):
        """Student search box of the 360° screen (respects access rules)."""
        _check_360_viewer(self.env)
        students = self.search(['|', ('name', 'ilike', term or ''), ('admission_no', 'ilike', term or '')]
                               if 'admission_no' in self._fields else [('name', 'ilike', term or '')], limit=12)
        return [{'id': s.id, 'name': s.name,
                 'class': ' - '.join(filter(None, [s.class_id.name, s.section_id.name]))} for s in students]

    # ------------------------------------------------------------------
    def _get_360_profile(self, year=None):
        self.ensure_one()
        env = self.env
        date_from = year.date_start if year else False
        date_to = year.date_end if year else False

        def in_year(day):
            return day and (not year or date_from <= day <= date_to)

        # ================= ACADEMIC =================
        results = env['school.exam.result'].sudo().search([('student_id', '=', self.id)])
        epoch = fields.Date.from_string('1900-01-01')
        by_exam = defaultdict(list)
        for res in results:
            by_exam[res.exam_id].append(res)
        exams = []
        for exam, rows in by_exam.items():
            dates = [r.exam_subject_id.date for r in rows if r.exam_subject_id.date]
            exams.append({'name': exam.name, 'date': min(dates) if dates else epoch,
                          'avg': round(sum(r.percentage for r in rows) / len(rows), 1),
                          'failed': len([r for r in rows if r.result_status == 'fail'])})
        exams.sort(key=lambda e: e['date'])
        year_exams = [e for e in exams if in_year(e['date'])] or exams
        overall = round(sum(e['avg'] for e in year_exams) / len(year_exams), 1) if year_exams else None
        trend = None
        if len(exams) >= 2:
            delta = exams[-1]['avg'] - exams[-2]['avg']
            trend = 'up' if delta >= 3 else ('down' if delta <= -3 else 'steady')

        by_subject = defaultdict(list)
        for res in results:
            by_subject[res.subject_id].append((res.exam_subject_id.date or epoch, res.exam_id.id, res.percentage))
        subjects = []
        for subject, series in by_subject.items():
            series.sort()
            values = [v for _d, _e, v in series]
            avg = round(sum(values) / len(values), 1)
            last = round(values[-1], 1)
            change = round(values[-1] - values[-2], 1) if len(values) >= 2 else None
            status = 'strength' if avg >= STRENGTH_PCT else ('support' if avg < SUPPORT_PCT else 'ok')
            subjects.append({'name': subject.name, 'avg': avg, 'last': last, 'change': change,
                             'trend': None if change is None else ('up' if change >= 3 else
                                                                   ('down' if change <= -3 else 'steady')),
                             'status': status, 'history': [round(v, 1) for v in values[-5:]]})
        subjects.sort(key=lambda s: -s['avg'])

        Attendance = env['school.attendance'].sudo()
        att_domain = [('student_id', '=', self.id)]
        if 'session' in Attendance._fields:
            att_domain.append(('session', '=', 'morning'))
        if year:
            att_domain += [('date', '>=', date_from), ('date', '<=', date_to)]
        att = Attendance.search(att_domain)
        present = len(att.filtered(lambda a: a.status == 'present'))
        attendance = {'days': len(att), 'present': present, 'absent': len(att) - present,
                      'percent': round(100.0 * present / len(att), 1) if att else None}

        comp = env['school.student.competency'].sudo().search([('student_id', '=', self.id)], order='date desc, id desc')
        latest = {}
        for c in comp:
            latest.setdefault(c.competency_id.id, c)          # most recent assessment per competency
        level_label = dict(LEVELS)
        competencies = defaultdict(list)
        for c in latest.values():
            competencies[c.category].append({'name': c.competency_id.name, 'subject': c.subject_id.name or '',
                                             'level': int(c.level), 'label': level_label[c.level],
                                             'date': c.date.strftime('%d %b %Y')})
        for items in competencies.values():
            items.sort(key=lambda x: (-x['level'], x['name']))

        # ================= DEVELOPMENT =================
        regs = env['event.registration'].sudo().search([('student_id', '=', self.id), ('state', '!=', 'cancel'),
                                                          ('event_id.is_school_activity', '=', True)])
        regs = regs.filtered(lambda r: in_year(r.event_id.date_begin.date()) if r.event_id.date_begin else not year)
        place_label = {'first': _('1st'), 'second': _('2nd'), 'third': _('3rd')}
        activity_by_type = {}
        for key, label in (('sports', _('Sports')), ('arts', _('Arts')), ('cultural', _('Cultural Activities')),
                           ('academic', _('Academic Events'))):
            rows = regs.filtered(lambda r, key=key: r.event_id.school_activity_type == key)
            activity_by_type[key] = {
                'label': label, 'count': len(rows),
                'wins': len(rows.filtered('school_position')),
                'items': [{'name': r.event_id.name, 'date': r.event_id.date_begin.strftime('%d %b %Y'),
                           'place': place_label.get(r.school_position, '')} for r in rows[:6]],
            }
        Record = env['school.student.record'].sudo()
        recs = Record.search([('student_ids', 'in', self.id)] + (
            [('date', '>=', date_from), ('date', '<=', date_to)] if year else []))
        kind_label = dict(RECORD_KINDS)
        level_names = dict(RECORD_LEVELS)

        def rec_items(kinds):
            rows = recs.filtered(lambda r: r.kind in kinds)
            return [{'name': r.name, 'kind': kind_label[r.kind], 'date': r.date.strftime('%d %b %Y'),
                     'level': level_names.get(r.level, ''), 'result': r.result or '', 'hours': r.hours}
                    for r in rows]

        competitions = rec_items(('competition',)) + [
            {'name': r.event_id.name, 'kind': _('School Activity'), 'date': r.event_id.date_begin.strftime('%d %b %Y'),
             'level': _('School'), 'result': place_label.get(r.school_position, ''), 'hours': 0}
            for r in regs.filtered('school_position')]
        clubs = [{'name': m.club_id.name, 'type': dict(m.club_id._fields['club_type'].selection).get(m.club_type),
                  'role': dict(m._fields['role'].selection).get(m.role), 'current': m.is_current}
                 for m in self.club_membership_ids.sudo()]
        leadership = []
        if self.leader_role:
            leadership.append({'name': self.leader_role, 'kind': _('Student Leader'), 'date': '', 'level': '',
                               'result': '', 'hours': 0})
        leadership += [{'name': '%s – %s' % (c['role'], c['name']), 'kind': _('Club'), 'date': '', 'level': '',
                        'result': '', 'hours': 0} for c in clubs if c['role'] != dict(
                            self.env['school.club.membership']._fields['role'].selection)['member'] and c['current']]
        leadership += rec_items(('leadership',))
        skills = rec_items(('skill',)) + [
            {'name': c['name'], 'kind': _('Life Skill'), 'date': c['date'], 'level': c['label'], 'result': '', 'hours': 0}
            for c in competencies.get('skill', []) if c['level'] >= 3]

        # ================= READING & CREATIVITY =================
        reading = {
            'books_read': self.books_read_count if 'books_read_count' in self._fields else 0,
            'last_12_months': self.books_read_this_year if 'books_read_this_year' in self._fields else 0,
            'per_month': self.reading_frequency if 'reading_frequency' in self._fields else 0,
            'genres': self.favourite_genre_ids.mapped('name') if 'favourite_genre_ids' in self._fields else [],
            'level': dict(self._fields['reading_level'].selection).get(
                self.reading_level or self.suggested_reading_level) if 'reading_level' in self._fields else '',
            'reviews': len(self.book_review_ids) if 'book_review_ids' in self._fields else 0,
        }

        # ================= SOCIAL RESPONSIBILITY =================
        social = {}
        for key in ('community_service', 'environmental', 'volunteering', 'service_achievement'):
            rows = recs.filtered(lambda r, key=key: r.kind == key)
            social[key] = {'label': kind_label[key], 'count': len(rows), 'hours': round(sum(rows.mapped('hours')), 1),
                           'items': rec_items((key,))[:6]}
        HousePoint = env['school.house.point'].sudo() if 'school.house.point' in env else None
        community_points = 0
        if HousePoint is not None:
            hp = HousePoint.search([('student_ids', 'in', self.id), ('state', '=', 'confirmed'),
                                    ('nature', '=', 'community')] + (
                [('date', '>=', date_from), ('date', '<=', date_to)] if year else []))
            community_points = int(sum(hp.mapped('points')))

        # ================= STRENGTHS / GAPS / SUPPORT =================
        # Strengths: what the student does well.
        # Learning gaps: what has not been mastered yet.
        # Areas requiring support: where the school should step in.
        strengths, gaps, support = [], [], []
        for s in subjects:
            if s['status'] == 'strength':
                strengths.append(_("Strong in %(subject)s (average %(avg).0f%%)", subject=s['name'], avg=s['avg']))
            elif s['status'] == 'support':
                gaps.append(_("%(subject)s: average %(avg).0f%%", subject=s['name'], avg=s['avg']))
            if s['change'] is not None and s['change'] <= -FALL_POINTS:
                support.append(_("%(subject)s fell by %(n).0f points in the last exam", subject=s['name'], n=-s['change']))
        for cat_items in competencies.values():
            for c in cat_items:
                if c['level'] == 4:
                    strengths.append(_("Advanced: %s", c['name']))
                elif c['level'] == 1:
                    gaps.append(_("Beginning level: %s", c['name']))
        if exams and exams[-1]['failed']:
            gaps.append(_("%s paper(s) failed in the latest exam", exams[-1]['failed']))
        wins = [c for c in competitions if c['result']]
        if wins:
            strengths.append(_("%s competition result(s) / prize(s)", len(wins)))
        lead_roles = [x for x in leadership]
        if lead_roles:
            strengths.append(_("Leadership: %s", ', '.join(x['name'] for x in lead_roles[:2])))
        service_hours_total = sum(r.hours for r in recs if r.kind in (
            'community_service', 'environmental', 'volunteering'))
        if service_hours_total >= 10:
            strengths.append(_("Committed to service (%.0f hours)", service_hours_total))
        per_month = self.reading_frequency if 'reading_frequency' in self._fields else 0
        if per_month >= 1:
            strengths.append(_("Keen reader (%s books a month)", per_month))
        if attendance['percent'] is not None and attendance['percent'] < LOW_ATTENDANCE:
            support.append(_("Attendance is %(p).0f%% (below %(l).0f%%)", p=attendance['percent'], l=LOW_ATTENDANCE))
        if not regs and not recs.filtered(lambda r: r.kind in ('competition', 'project', 'achievement')) \
                and not self.club_membership_ids:
            support.append(_("No co-curricular participation recorded this year"))
        if 'books_read_this_year' in self._fields and not self.books_read_this_year:
            support.append(_("No library books read in the last 12 months"))
        # confirmed early-warning status (only for staff allowed to see it)
        if 'wellbeing_status' in self._fields and self.env.user.has_group('ad_school_management.group_school_teacher'):
            ews_status = self.sudo().wellbeing_status
            if ews_status in ('amber', 'red'):
                support.append(_("Early warning reviewed: %s",
                                 dict(self._fields['wellbeing_status'].selection)[ews_status]))

        # ================= BEHAVIOUR & PARTICIPATION (quarterly / half-yearly) =================
        rating_labels = dict(BEHAVIOUR_RATINGS)
        period_labels = dict(REVIEW_PERIODS)
        period_order = [k for k, _l in REVIEW_PERIODS]
        reviews = env['school.student.behaviour'].sudo().search(
            [('student_ids', 'in', self.id)] + ([('academic_year_id', '=', year.id)] if year else []))
        # this student's own self-reflection / parent feedback lines
        fb_by_review = {f.review_id.id: f for f in env['school.student.behaviour.feedback'].sudo().search(
            [('student_id', '=', self.id), ('review_id', 'in', reviews.ids)])}
        behaviour_reviews = [{
            'id': r.id, 'period': period_labels.get(r.period),
            'behaviour': int(r.behaviour), 'behaviour_label': rating_labels.get(r.behaviour),
            'discipline': int(r.discipline), 'discipline_label': rating_labels.get(r.discipline),
            'participation': int(r.participation), 'participation_label': rating_labels.get(r.participation),
            'observation': r.teacher_observation or '',
            'reflection': (fb_by_review.get(r.id).self_reflection if fb_by_review.get(r.id) else '') or '',
            'parent_feedback': (fb_by_review.get(r.id).parent_feedback if fb_by_review.get(r.id) else '') or '',
            'date': r.date.strftime('%d %b %Y'),
        } for r in reviews.sorted(lambda r: (period_order.index(r.period), r.id))]

        profile = {
            'student': {'id': self.id, 'name': self.name,
                        'class': ' - '.join(filter(None, [self.class_id.name, self.section_id.name])),
                        'house': self.house_id.name if 'house_id' in self._fields else '',
                        'admission_no': self.admission_no if 'admission_no' in self._fields else '',
                        'leader_role': self.leader_role or ''},
            'academic': {'overall': overall, 'trend': trend, 'exams': year_exams[-6:], 'subjects': subjects,
                         'attendance': attendance},
            'competencies': {key: {'label': label, 'items': competencies.get(key, [])}
                             for key, label in COMPETENCY_CATEGORIES},
            'strengths': strengths, 'gaps': gaps, 'support': support,
            'activities': activity_by_type,
            'clubs': clubs, 'competitions': competitions, 'leadership': leadership,
            'projects': rec_items(('project',)), 'skills': skills,
            'certifications': rec_items(('certification',)), 'achievements': rec_items(('achievement',)) + [
                c for c in competitions if c['result']],
            'reading': reading, 'social': social, 'community_points': community_points,
            'behaviour_reviews': behaviour_reviews,
        }
        profile['summary'] = self._360_summary(profile)
        return profile

    def _360_summary(self, p):
        """A holistic profile in plain sentences, built from the data."""
        self.ensure_one()
        first = (self.name or '').split(' ')[0]
        lines = []
        a = p['academic']
        if a['overall'] is not None:
            trend = {'up': _("and improving"), 'down': _("but falling in the latest exam"),
                     'steady': _("and steady"), None: ''}[a['trend']]
            lines.append(_("%(n)s's overall academic average is %(avg).0f%% %(trend)s.",
                           n=first, avg=a['overall'], trend=trend).replace(' .', '.'))
            best = [s for s in a['subjects'] if s['status'] == 'strength'][:2]
            weak = [s for s in a['subjects'] if s['status'] == 'support' or (s['change'] or 0) <= -FALL_POINTS][:2]
            if best:
                lines.append(_("Strongest in %s.", _(" and ").join('%s (%.0f%%)' % (s['name'], s['avg']) for s in best)))
            if weak:
                lines.append(_("Needs support in %s.", _(" and ").join('%s (%.0f%%)' % (s['name'], s['last']) for s in weak)))
        else:
            lines.append(_("No exam results recorded yet."))
        att = a['attendance']
        if att['percent'] is not None:
            lines.append(_("Attendance %(p).0f%% (%(a)s day(s) absent).", p=att['percent'], a=att['absent']))
        adv = [c['name'] for items in p['competencies'].values() for c in items['items'] if c['level'] >= 3]
        if adv:
            lines.append(_("Demonstrates %s at proficient level or above.", ', '.join(adv[:3])))
        acts = [(k, v) for k, v in p['activities'].items() if v['count']]
        if acts:
            words = {'sports': _('sports'), 'arts': _('arts'), 'cultural': _('cultural'), 'academic': _('academic')}
            parts = ['%s %s %s' % (v['count'], words[k], _('activity') if v['count'] == 1 else _('activities'))
                     for k, v in acts]
            acts = [v for _k, v in acts]
            wins = sum(v['wins'] for v in acts)
            lines.append(_("Took part in %(parts)s%(wins)s.", parts=', '.join(parts),
                           wins=_(", winning %s place(s)", wins) if wins else ''))
        if p['clubs']:
            lines.append(_("Member of %s.", ', '.join('%s (%s)' % (c['name'], c['role']) for c in p['clubs'] if c['current'])))
        if p['leadership']:
            lines.append(_("Leadership: %s.", ', '.join(x['name'] for x in p['leadership'][:3])))
        extra = [(len(p['projects']), _("project(s)")), (len(p['certifications']), _("certification(s)")),
                 (len(p['skills']), _("skill(s)"))]
        extra = ['%s %s' % (n, label) for n, label in extra if n]
        if extra:
            lines.append(_("Has completed %s.", ', '.join(extra)))
        r = p['reading']
        if r['books_read']:
            lines.append(_("Reads about %(m)s book(s) a month (%(n)s read)%(g)s.", m=r['per_month'], n=r['books_read'],
                           g=_(", enjoys %s", ', '.join(r['genres'])) if r['genres'] else ''))
        service_hours = sum(v['hours'] for v in p['social'].values())
        service_count = sum(v['count'] for v in p['social'].values())
        if service_count or p['community_points']:
            lines.append(_("Social responsibility: %(c)s activity(ies), %(h)s hour(s) of service%(pts)s.",
                           c=service_count, h=service_hours,
                           pts=_(", %s community house point(s)", p['community_points']) if p['community_points'] else ''))
        return lines