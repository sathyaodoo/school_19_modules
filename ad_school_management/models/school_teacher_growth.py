"""Teacher Growth Portfolio (BRS Part XV-19).

Tracks a teacher's professional development: training, certifications,
workshops, webinars, demonstration classes, peer observation, lesson study,
research, publications, innovations (PD activities), self-reflections and
annual professional-development goals, with a dedicated dashboard.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

PD_MANAGER_GROUPS = ('ad_school_management.group_school_principal',
                     'ad_school_management.group_school_hr_manager',
                     'ad_school_management.group_school_admin')


def _is_pd_manager(env):
    return env.is_superuser() or any(env.user.has_group(g) for g in PD_MANAGER_GROUPS)


def _is_school_admin(env):
    """Only the School Admin sees the per-teacher list and other teachers' portfolios."""
    return env.is_superuser() or env.user.has_group('ad_school_management.group_school_admin')


def _current_teacher(env):
    return env['school.teacher'].sudo().search([('user_id', '=', env.uid)], limit=1)


def _year_of(env, day):
    if not day:
        return env['school.academic.year']
    return env['school.academic.year'].sudo().search(
        [('date_start', '<=', day), ('date_end', '>=', day)], limit=1)


# ======================================================================
# Activity types (the 10 BRS activity types are created as data)
# ======================================================================
class SchoolPdActivityType(models.Model):
    _name = 'school.pd.activity.type'
    _description = 'Professional Development Activity Type'
    _order = 'sequence, name'

    name = fields.Char(string='Activity Type', required=True, translate=True)
    code = fields.Char(string='Code', readonly=True, copy=False,
                       help='Technical code of the built-in BRS types (decides which extra fields are shown).')
    sequence = fields.Integer(default=10)
    icon = fields.Char(string='Icon', default='fa-graduation-cap', help='Font Awesome icon, e.g. fa-book')
    counts_hours = fields.Boolean(string='Counts CPD Hours', default=True,
                                  help='Hours of this type count towards the annual CPD hours target.')
    description = fields.Text()
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This activity type already exists!')


# ======================================================================
# PD activities
# ======================================================================
class SchoolPdActivity(models.Model):
    _name = 'school.pd.activity'
    _description = 'Professional Development Activity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Title', required=True, tracking=True,
                       help='e.g. "CBSE Capacity Building: Competency-Based Assessment"')
    teacher_id = fields.Many2one('school.teacher', string='Teacher', required=True, index=True, tracking=True,
                                 default=lambda self: _current_teacher(self.env))
    teacher_user_id = fields.Many2one(related='teacher_id.user_id', string='Teacher User', store=True)
    type_id = fields.Many2one('school.pd.activity.type', string='Activity Type', required=True, tracking=True,
                              ondelete='restrict')
    type_code = fields.Char(related='type_id.code')
    date_start = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(string='End Date')
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year',
                                       compute='_compute_academic_year', store=True, index=True)
    hours = fields.Float(string='Hours', tracking=True, help='Duration in hours (counts towards CPD hours).')
    provider = fields.Char(string='Provider / Organiser',
                           help='e.g. CBSE, SCERT, DIET, university, publisher, the school itself')
    mode = fields.Selection([('in_person', 'In Person'), ('online', 'Online'), ('blended', 'Blended')],
                            string='Mode', default='in_person')
    role = fields.Selection([('participant', 'Participant'), ('presenter', 'Presenter / Resource Person'),
                             ('organiser', 'Organiser'), ('observer', 'Observer'), ('observed', 'Observed Teacher'),
                             ('author', 'Author / Researcher')], string='My Role', default='participant')
    description = fields.Text(string='What I Learned / Summary')
    impact = fields.Text(string='Impact on Teaching',
                         help='How it changed your classroom practice or student learning.')
    # type-specific details
    certificate = fields.Binary(string='Certificate / Evidence', attachment=True)
    certificate_filename = fields.Char()
    certificate_number = fields.Char(string='Certificate No.')
    valid_until = fields.Date(string='Valid Until')
    link = fields.Char(string='Link', help='Publication, research paper, recording or course link.')
    peer_teacher_ids = fields.Many2many('school.teacher', 'school_pd_activity_peer_rel', 'activity_id', 'teacher_id',
                                        string='Peer Teachers',
                                        help='Teachers observed / observing, or the lesson-study group.')
    class_id = fields.Many2one('school.class', string='Class')
    subject_id = fields.Many2one('school.subject', string='Subject')
    # Simple workflow: Draft -> Submitted. No Principal verification step;
    # submitted activities count towards CPD hours and goals.
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted')], string='Status',
                             default='draft', required=True, tracking=True, index=True)

    @api.depends('date_start')
    def _compute_academic_year(self):
        for rec in self:
            rec.academic_year_id = _year_of(self.env, rec.date_start)

    @api.constrains('hours', 'date_start', 'date_end')
    def _check_values(self):
        for rec in self:
            if rec.hours < 0:
                raise ValidationError(_("Hours cannot be negative."))
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("The end date cannot be before the start date."))

    # --- teachers edit only their own drafts -----------------------------
    _TEACHER_LOCKED = ('submitted',)

    def write(self, vals):
        if not _is_pd_manager(self.env) and not self.env.context.get('school_pd_workflow'):
            locked = self.filtered(lambda r: r.state in self._TEACHER_LOCKED)
            if locked and set(vals) - {'message_main_attachment_id'}:
                raise UserError(_("A submitted activity can only be changed by the Principal / HR / School Admin. "
                                  "Ask them to set it back to draft."))
        return super().write(vals)

    def unlink(self):
        if not _is_pd_manager(self.env) and self.filtered(lambda r: r.state in self._TEACHER_LOCKED):
            raise UserError(_("A submitted activity cannot be deleted."))
        return super().unlink()

    # --- workflow ---------------------------------------------------------
    def action_submit(self):
        for rec in self.filtered(lambda r: r.state == 'draft'):
            if rec.type_id.counts_hours and not rec.hours:
                raise UserError(_("Enter the hours for '%s' before submitting.", rec.name))
            rec.with_context(school_pd_workflow=True).write({'state': 'submitted'})

    def action_reset_draft(self):
        """Principal / HR / School Admin can re-open a submitted activity for correction."""
        if not _is_pd_manager(self.env):
            raise UserError(_("Only the Principal, HR Manager or School Admin can set a submitted activity back to draft."))
        self.filtered(lambda r: r.state == 'submitted').write({'state': 'draft'})

    # ------------------------------------------------------------------
    # Growth dashboard data
    # ------------------------------------------------------------------
    @api.model
    def get_growth_dashboard(self, teacher_id=False, year_id=False):
        """Data for the Teacher Growth dashboard.

        Teachers always get their own portfolio. Principal / HR / Admin get
        the school overview, or one teacher's portfolio when teacher_id is set."""
        manager = _is_pd_manager(self.env)
        me = _current_teacher(self.env)
        Year = self.env['school.academic.year'].sudo()
        year = Year.browse(year_id) if year_id else _year_of(self.env, fields.Date.context_today(self))
        if not year:
            year = Year.search([], order='date_start desc', limit=1)
        years = [{'id': y.id, 'name': y.name} for y in Year.search([], order='date_start desc')]
        target = self.env.company.pd_annual_hours_target or 0

        is_admin = _is_school_admin(self.env)
        if not manager:
            teacher = me
        elif teacher_id and (is_admin or teacher_id == me.id):
            # only the School Admin may open another teacher's portfolio
            teacher = self.env['school.teacher'].sudo().browse(teacher_id)
        else:
            teacher = self.env['school.teacher']

        result = {'is_manager': manager, 'is_admin': is_admin,
                  'year': {'id': year.id, 'name': year.name} if year else False,
                  'years': years, 'target_hours': target,
                  # Staff Leave Requests panel (visible to Admin / HR / Principal only)
                  'leaves': self.env['school.dashboard']._get_leave_stats()}
        if teacher:
            result['portfolio'] = teacher._growth_portfolio(year)
        elif manager:
            overview = self._growth_overview(year, target)
            if not is_admin:
                # Principal / HR: school totals only, no per-teacher list
                overview['teachers'] = []
            result['overview'] = overview
            if me:
                # Principal / HR / Admin who are also teachers: their own
                # personal portfolio (goals, recent activities ...) as well
                result['my_portfolio'] = me._growth_portfolio(year)
        else:
            result['no_teacher'] = True
        return result

    @api.model
    def _growth_overview(self, year, target):
        Activity = self.sudo()
        teachers = self.env['school.teacher'].sudo().search([])
        domain = [('academic_year_id', '=', year.id)] if year else []
        rows = []
        for teacher in teachers:
            acts = Activity.search(domain + [('teacher_id', '=', teacher.id)])
            submitted = acts.filtered(lambda a: a.state == 'submitted')
            hours = sum(submitted.filtered(lambda a: a.type_id.counts_hours).mapped('hours'))
            goals = self.env['school.teacher.pd.goal'].sudo().search(
                [('teacher_id', '=', teacher.id)] + ([('academic_year_id', '=', year.id)] if year else []))
            last_reflection = self.env['school.teacher.reflection'].sudo().search(
                [('teacher_id', '=', teacher.id)], order='date desc', limit=1)
            rows.append({
                'id': teacher.id, 'name': teacher.name,
                'hours': round(hours, 1),
                'percent': min(100, round(100.0 * hours / target)) if target else 0,
                'below_target': bool(target and hours < target),
                'activities': len(submitted),
                'goals_met': len(goals.filtered('is_met')), 'goals': len(goals),
                'last_reflection': last_reflection.date.strftime('%d %b %Y') if last_reflection else '',
            })
        rows.sort(key=lambda r: (-r['hours'], r['name']))
        all_acts = Activity.search(domain + [('state', '=', 'submitted')])
        by_type = []
        for t in self.env['school.pd.activity.type'].sudo().search([]):
            by_type.append({'id': t.id, 'name': t.name, 'icon': t.icon or 'fa-graduation-cap',
                            'count': len(all_acts.filtered(lambda a, t=t: a.type_id == t))})
        return {
            'teachers': rows,
            'teacher_count': len(rows),
            'below_target': len([r for r in rows if r['below_target']]),
            'total_hours': round(sum(r['hours'] for r in rows), 1),
            'avg_hours': round(sum(r['hours'] for r in rows) / len(rows), 1) if rows else 0,
            'by_type': by_type,
        }


# ======================================================================
# Self-reflection (private to the teacher unless shared)
# ======================================================================
class SchoolTeacherReflection(models.Model):
    _name = 'school.teacher.reflection'
    _description = 'Teacher Self-Reflection'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Title', required=True, default=lambda self: _("Reflection"),
                       help='e.g. "Term 1 – Teaching fractions with manipulatives"')
    teacher_id = fields.Many2one('school.teacher', string='Teacher', required=True, index=True,
                                 default=lambda self: _current_teacher(self.env))
    teacher_user_id = fields.Many2one(related='teacher_id.user_id', store=True)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year',
                                       compute='_compute_academic_year', store=True)
    went_well = fields.Text(string='What went well?')
    challenges = fields.Text(string='What was challenging?')
    learnings = fields.Text(string='What did I learn?')
    next_steps = fields.Text(string='What will I do next?')
    activity_ids = fields.Many2many('school.pd.activity', string='Related PD Activities')
    shared = fields.Boolean(string='Share with Principal', tracking=True,
                            help='Reflections are private. Tick to let the Principal / HR read this one.')
    principal_comment = fields.Text(string='Principal Feedback')

    @api.depends('date')
    def _compute_academic_year(self):
        for rec in self:
            rec.academic_year_id = _year_of(self.env, rec.date)

    def write(self, vals):
        # Principal / HR may only add feedback to shared reflections
        if _is_pd_manager(self.env) and not self.env.is_superuser():
            others = self.filtered(lambda r: r.teacher_id.user_id != self.env.user)
            if others and set(vals) - {'principal_comment'}:
                raise UserError(_("Only the teacher can change their reflection; you can add Principal Feedback."))
        return super().write(vals)


# ======================================================================
# Annual professional-development goals
# ======================================================================
class SchoolTeacherPdGoal(models.Model):
    _name = 'school.teacher.pd.goal'
    _description = 'Annual Professional-Development Goal'
    _inherit = ['mail.thread']
    _order = 'academic_year_id desc, sequence, id'

    name = fields.Char(string='Goal', required=True, tracking=True,
                       help='e.g. "Complete 50 hours of CPD" or "Run 2 demonstration classes"')
    sequence = fields.Integer(default=10)
    teacher_id = fields.Many2one('school.teacher', string='Teacher', required=True, index=True,
                                 default=lambda self: _current_teacher(self.env))
    teacher_user_id = fields.Many2one(related='teacher_id.user_id', store=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True,
                                       default=lambda self: _year_of(self.env, fields.Date.context_today(self)))
    measure = fields.Selection([('hours', 'CPD Hours'), ('count', 'Number of Activities'),
                                ('qualitative', 'Qualitative (no number)')],
                               string='Measured By', required=True, default='count')
    type_id = fields.Many2one('school.pd.activity.type', string='Activity Type',
                              help='Count only this type (leave empty to count every activity type).')
    target = fields.Float(string='Target', default=1)
    achieved = fields.Float(string='Achieved', compute='_compute_progress')
    progress = fields.Float(string='Progress (%)', compute='_compute_progress')
    is_met = fields.Boolean(string='Goal Met', compute='_compute_progress',
                            help='Measured goals: target reached with submitted activities. '
                                 'Qualitative goals: marked achieved by the Principal.')
    deadline = fields.Date(string='Deadline')
    teacher_note = fields.Text(string='My Plan / Notes')
    principal_comment = fields.Text(string='Principal Comment')
    state = fields.Selection([('planned', 'Planned'), ('approved', 'Approved'), ('achieved', 'Achieved'),
                              ('not_achieved', 'Not Achieved')], string='Status', default='planned',
                             required=True, tracking=True)

    @api.depends('measure', 'type_id', 'target', 'teacher_id', 'academic_year_id', 'state')
    def _compute_progress(self):
        Activity = self.env['school.pd.activity'].sudo()
        for goal in self:
            if goal.measure == 'qualitative' or not goal.teacher_id or not goal.academic_year_id:
                goal.achieved = 0
                goal.progress = 100.0 if goal.state == 'achieved' else 0.0
                goal.is_met = goal.state == 'achieved'
                continue
            domain = [('teacher_id', '=', goal.teacher_id.id), ('academic_year_id', '=', goal.academic_year_id.id),
                      ('state', '=', 'submitted')]
            if goal.type_id:
                domain.append(('type_id', '=', goal.type_id.id))
            acts = Activity.search(domain)
            if goal.measure == 'hours':
                goal.achieved = sum(acts.filtered(lambda a: a.type_id.counts_hours).mapped('hours'))
            else:
                goal.achieved = len(acts)
            goal.progress = min(100.0, 100.0 * goal.achieved / goal.target) if goal.target else 0.0
            goal.is_met = bool(goal.target) and goal.achieved >= goal.target

    @api.constrains('target', 'measure')
    def _check_target(self):
        for goal in self:
            if goal.measure != 'qualitative' and goal.target <= 0:
                raise ValidationError(_("Set a target greater than 0 (or choose a qualitative goal)."))

    def _check_manager(self):
        if not _is_pd_manager(self.env):
            raise UserError(_("Only the Principal, HR Manager or School Admin can approve or close goals."))

    def action_approve(self):
        self._check_manager()
        self.filtered(lambda g: g.state == 'planned').write({'state': 'approved'})

    def action_mark_achieved(self):
        self._check_manager()
        self.write({'state': 'achieved'})

    def action_mark_not_achieved(self):
        self._check_manager()
        self.write({'state': 'not_achieved'})

    def write(self, vals):
        if not _is_pd_manager(self.env) and 'state' in vals:
            raise UserError(_("Only the Principal, HR Manager or School Admin can change a goal's status."))
        if not _is_pd_manager(self.env) and self.filtered(lambda g: g.state in ('achieved', 'not_achieved')):
            raise UserError(_("A closed goal can no longer be changed."))
        return super().write(vals)


# ======================================================================
# Teacher: portfolio summary
# ======================================================================
class SchoolTeacherGrowth(models.Model):
    _inherit = 'school.teacher'

    pd_activity_ids = fields.One2many('school.pd.activity', 'teacher_id', string='PD Activities')
    pd_goal_ids = fields.One2many('school.teacher.pd.goal', 'teacher_id', string='PD Goals')
    pd_hours_this_year = fields.Float(string='CPD Hours (This Year)', compute='_compute_pd_summary')
    pd_target_hours = fields.Float(string='CPD Target (Hours)', compute='_compute_pd_summary')
    pd_activity_count = fields.Integer(string='PD Activities (This Year)', compute='_compute_pd_summary')
    pd_goal_count = fields.Integer(string='Goals (This Year)', compute='_compute_pd_summary')
    pd_goals_met = fields.Integer(string='Goals Met', compute='_compute_pd_summary')

    def _compute_pd_summary(self):
        year = _year_of(self.env, fields.Date.context_today(self))
        target = self.env.company.pd_annual_hours_target or 0
        Activity = self.env['school.pd.activity'].sudo()
        Goal = self.env['school.teacher.pd.goal'].sudo()
        for teacher in self:
            acts = Activity.search([('teacher_id', '=', teacher.id), ('academic_year_id', '=', year.id),
                                    ('state', '=', 'submitted')]) if year and teacher.id else Activity
            goals = Goal.search([('teacher_id', '=', teacher.id), ('academic_year_id', '=', year.id)]) \
                if year and teacher.id else Goal
            teacher.pd_hours_this_year = sum(acts.filtered(lambda a: a.type_id.counts_hours).mapped('hours'))
            teacher.pd_target_hours = target
            teacher.pd_activity_count = len(acts)
            teacher.pd_goal_count = len(goals)
            teacher.pd_goals_met = len(goals.filtered('is_met'))

    def _growth_portfolio(self, year):
        """One teacher's portfolio for the dashboard and the PDF."""
        self.ensure_one()
        target = self.env.company.pd_annual_hours_target or 0
        Activity = self.env['school.pd.activity'].sudo()
        domain = [('teacher_id', '=', self.id)] + ([('academic_year_id', '=', year.id)] if year else [])
        acts = Activity.search(domain)
        submitted = acts.filtered(lambda a: a.state == 'submitted')
        hours = sum(submitted.filtered(lambda a: a.type_id.counts_hours).mapped('hours'))
        types = []
        for t in self.env['school.pd.activity.type'].sudo().search([]):
            t_acts = submitted.filtered(lambda a, t=t: a.type_id == t)
            types.append({'id': t.id, 'name': t.name, 'icon': t.icon or 'fa-graduation-cap',
                          'count': len(t_acts), 'hours': round(sum(t_acts.mapped('hours')), 1)})
        goals = self.env['school.teacher.pd.goal'].sudo().search(
            [('teacher_id', '=', self.id)] + ([('academic_year_id', '=', year.id)] if year else []))
        reflections = self.env['school.teacher.reflection'].sudo().search(
            [('teacher_id', '=', self.id)] + ([('academic_year_id', '=', year.id)] if year else []))
        state_labels = dict(Activity._fields['state']._description_selection(self.env))
        goal_labels = dict(self.env['school.teacher.pd.goal']._fields['state']._description_selection(self.env))
        return {
            'teacher': {'id': self.id, 'name': self.name},
            'hours': round(hours, 1),
            'target': target,
            'percent': min(100, round(100.0 * hours / target)) if target else 0,
            'activity_count': len(submitted),
            'drafts': len(acts.filtered(lambda a: a.state == 'draft')),
            'by_type': types,
            'reflection_count': len(reflections),
            'shared_reflections': len(reflections.filtered('shared')),
            'goals': [{'id': g.id, 'name': g.name, 'progress': round(g.progress), 'is_met': g.is_met,
                       'achieved': g.achieved, 'target': g.target, 'measure': g.measure,
                       'state': goal_labels.get(g.state)} for g in goals],
            'goals_met': len(goals.filtered('is_met')),
            'recent': [{'id': a.id, 'name': a.name, 'type': a.type_id.name, 'icon': a.type_id.icon or 'fa-graduation-cap',
                        'date': a.date_start.strftime('%d %b %Y'), 'hours': a.hours,
                        'state': state_labels.get(a.state), 'state_key': a.state}
                       for a in acts.sorted(lambda a: (a.date_start, a.id), reverse=True)[:8]],
        }

    def _growth_report_values(self):
        """Data for the printed Teacher Growth Portfolio (current academic year)."""
        self.ensure_one()
        year = _year_of(self.env, fields.Date.context_today(self))
        year_domain = [('academic_year_id', '=', year.id)] if year else []
        return {
            'year': year,
            'p': self._growth_portfolio(year),
            'acts': self.env['school.pd.activity'].sudo().search(
                [('teacher_id', '=', self.id), ('state', '=', 'submitted')] + year_domain, order='type_id, date_start'),
            # only reflections the teacher chose to share are printed
            'reflections': self.env['school.teacher.reflection'].sudo().search(
                [('teacher_id', '=', self.id), ('shared', '=', True)] + year_domain, order='date'),
        }

    def action_open_growth_dashboard(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'school_teacher_growth_dashboard',
                'name': _('Growth Portfolio – %s', self.name), 'params': {'teacher_id': self.id}}

    def action_print_growth_portfolio(self):
        return self.env.ref('ad_school_management.action_report_teacher_growth_portfolio').report_action(self)


class ResCompanyPd(models.Model):
    _inherit = 'res.company'

    pd_annual_hours_target = fields.Float(string='Annual CPD Hours Target', default=50,
                                          help='Hours of professional development each teacher should complete '
                                               'per academic year (CBSE: 50 hours).')


class ResConfigSettingsPd(models.TransientModel):
    _inherit = 'res.config.settings'

    pd_annual_hours_target = fields.Float(related='company_id.pd_annual_hours_target', readonly=False)