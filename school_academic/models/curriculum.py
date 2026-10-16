# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

APPROVER_GROUPS = (
    'ad_school_management.group_school_principal',
    'ad_school_management.group_school_admin',
    'base.group_system',
)


def approver_users(env):
    """Users of the principal / admin groups (they approve lesson plans)."""
    groups = env['res.groups']
    for xmlid in APPROVER_GROUPS[:2]:
        groups |= env.ref(xmlid)
    return env['res.users'].sudo().search([('group_ids', 'in', groups.ids), ('share', '=', False)])


def current_teacher(env):
    """The school.teacher record of the logged-in user (empty for admin / users without a teacher record)."""
    return env['school.teacher'].sudo().search([('user_id', '=', env.uid)], limit=1)


def is_approver(env):
    """Principal, school admin or system administrator (or sudo / tests)."""
    return env.su or any(env.user.has_group(g) for g in APPROVER_GROUPS)


class SchoolCurriculum(models.Model):
    _name = 'school.curriculum'
    _inherit = ['mail.thread']
    _description = 'Curriculum (class + academic year)'
    _order = 'academic_year_id desc, class_id, id desc'

    name = fields.Char(string='Curriculum Name', required=True)
    company_id = fields.Many2one('res.company', string='School / Board', required=True,
                                 default=lambda self: self.env.company)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True)
    class_id = fields.Many2one(
        'school.class', string='Class', index=True,
        help="Chosen in the Class column of the first topic row of the Subjects tab. All topics of a curriculum "
             "are for this one class.")
    state = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published'), ('done', 'Done'), ('archived', 'Archived')],
        string='Status', default='draft', required=True, index=True, tracking=True,
        help="Done = every topic of the topic plan is Completed.")
    can_edit_structure = fields.Boolean(
        compute='_compute_can_edit_structure',
        help="Draft: teachers and the principal can type in the rows. After publishing: the principal / admin only.")
    teacher_id = fields.Many2one(
        'school.teacher', string='Teacher', default=lambda self: current_teacher(self.env),
        help="Filled with the logged-in teacher. The teacher who prepared this curriculum.")
    teacher_user_id = fields.Many2one(related='teacher_id.user_id', store=True, string='Teacher Login')
    year_start = fields.Date(related='academic_year_id.date_start', string='Year Starts')
    year_end = fields.Date(related='academic_year_id.date_end', string='Year Ends')
    teaching_weeks = fields.Integer(
        string='Teaching Weeks', default=36,
        help="Used to calculate the annual periods of a subject (periods per week x teaching weeks).")
    description = fields.Text(string='Overview & Objectives')
    line_ids = fields.One2many('school.curriculum.line', 'curriculum_id', string='Subjects')
    subject_ids = fields.Many2many('school.subject', compute='_compute_subject_ids', string='Subjects in Curriculum')
    plan_ids = fields.One2many('school.curriculum.plan', 'curriculum_id', string='Topic Plan')
    plan_count = fields.Integer(compute='_compute_plan_count', string='Topics Planned')
    plan_done_count = fields.Integer(compute='_compute_plan_count', string='Topics Completed')
    plan_progress = fields.Float(compute='_compute_plan_count', string='Completed %')
    subject_count = fields.Integer(compute='_compute_totals', string='Subject Count')
    periods_per_week = fields.Float(compute='_compute_totals', string='Periods / Week')
    total_periods = fields.Integer(compute='_compute_totals', string='Annual Periods')
    approved_by = fields.Many2one('res.users', string='Published By', readonly=True)
    approved_datetime = fields.Datetime(string='Published On', readonly=True)
    syllabus_count = fields.Integer(compute='_compute_syllabus_count', string='Syllabus Count')

    def _compute_syllabus_count(self):
        Syllabus = self.env['school.syllabus']
        for rec in self:
            rec.syllabus_count = Syllabus.search_count(rec._syllabus_domain()) if rec.id else 0

    def _syllabus_domain(self):
        self.ensure_one()
        return [('class_id', '=', self.class_id.id), ('academic_year_id', '=', self.academic_year_id.id),
                ('company_id', '=', self.company_id.id)]

    def action_view_syllabus(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Syllabus'), 'res_model': 'school.syllabus',
                'view_mode': 'list,form', 'domain': self._syllabus_domain(),
                'context': {'default_class_id': self.class_id.id, 'default_academic_year_id': self.academic_year_id.id,
                            'default_company_id': self.company_id.id}}

    def action_create_syllabus_drafts(self):
        """One draft syllabus for every class + section + subject of this (published) curriculum.
        Teachers are told. A subject without topic rows gets one syllabus for the whole class."""
        self.ensure_one()
        if self.state not in ('published', 'done'):
            raise UserError(_("Publish the curriculum first."))
        Syllabus = self.env['school.syllabus']
        combos, seen = [], set()
        for plan in self.plan_ids.sorted(lambda p: (p.subject_id.name or '', p.section_id.name or '')):
            key = (plan.section_id.id, plan.subject_id.id)
            if key not in seen:
                seen.add(key)
                combos.append((plan.section_id, plan.subject_id))
        for line in self.line_ids:
            if not any(key[1] == line.subject_id.id for key in seen):
                seen.add((False, line.subject_id.id))
                combos.append((self.env['school.section'], line.subject_id))
        created = Syllabus
        for section, subject in combos:
            exists = Syllabus.search([
                ('class_id', '=', self.class_id.id), ('academic_year_id', '=', self.academic_year_id.id),
                ('company_id', '=', self.company_id.id), ('subject_id', '=', subject.id),
                ('section_id', '=', section.id or False), ('state', '!=', 'archived')], limit=1)
            if exists:
                continue
            created |= Syllabus.create({
                'name': _("%(subject)s - %(cls)s%(section)s - %(year)s Syllabus", subject=subject.name,
                          cls=self.class_id.name, section=(' ' + section.name) if section else '',
                          year=self.academic_year_id.name),
                'company_id': self.company_id.id, 'academic_year_id': self.academic_year_id.id,
                'class_id': self.class_id.id, 'section_id': section.id, 'subject_id': subject.id})
        created._notify_teacher_to_prepare()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _("Syllabus drafts"), 'type': 'success', 'sticky': False,
            'message': _("%(new)s draft(s) created, %(old)s already had a syllabus.",
                         new=len(created), old=len(combos) - len(created)),
            'next': {'type': 'ir.actions.act_window_close'}}}

    # ------------------------------------------------------------------ computes
    @api.depends('state')
    @api.depends_context('uid')
    def _compute_can_edit_structure(self):
        approver = is_approver(self.env)
        for rec in self:
            rec.can_edit_structure = rec.state == 'draft' or approver

    @api.depends('line_ids.subject_id')
    def _compute_subject_ids(self):
        for rec in self:
            rec.subject_ids = rec.line_ids.mapped('subject_id')

    @api.depends('plan_ids', 'plan_ids.status')
    def _compute_plan_count(self):
        for rec in self:
            done = len(rec.plan_ids.filtered(lambda p: p.status == 'completed'))
            rec.plan_count = len(rec.plan_ids)
            rec.plan_done_count = done
            rec.plan_progress = (done * 100.0 / rec.plan_count) if rec.plan_count else 0.0

    def _update_done_state(self):
        """Published -> Done when every topic is Completed; back to Published when one is not."""
        for rec in self:
            if rec.state not in ('published', 'done'):
                continue
            all_done = bool(rec.plan_ids) and all(p.status == 'completed' for p in rec.plan_ids)
            new_state = 'done' if all_done else 'published'
            if new_state != rec.state:
                rec.sudo().write({'state': new_state})
                if new_state == 'done':
                    rec._notify_done()

    def _notify_done(self):
        self.ensure_one()
        users = approver_users(self.env) | self.teacher_user_id.sudo()
        if users:
            self.sudo().message_post(
                body=Markup(_("<p>Every topic of <b>%s</b> is completed. The curriculum is now <b>Done</b>.</p>")) % self.name,
                subject=_("Curriculum done: %s", self.name), partner_ids=users.mapped('partner_id').ids,
                message_type='notification', subtype_xmlid='mail.mt_comment')

    @api.depends('line_ids.periods_per_week', 'line_ids.total_periods')
    def _compute_totals(self):
        for rec in self:
            rec.subject_count = len(rec.line_ids)
            rec.periods_per_week = sum(rec.line_ids.mapped('periods_per_week'))
            rec.total_periods = sum(rec.line_ids.mapped('total_periods'))

    @api.onchange('plan_ids')
    def _onchange_plan_class(self):
        """The Class column of the first topic row becomes the class of the curriculum."""
        if not self.class_id:
            row = self.plan_ids.filtered('class_id')[:1]
            if row:
                self.class_id = row.class_id

    @api.onchange('class_id', 'academic_year_id')
    def _onchange_suggest_name(self):
        if self.class_id and self.academic_year_id and not self.name:
            self.name = _("%(cls)s - %(year)s Curriculum", cls=self.class_id.name, year=self.academic_year_id.name)

    @api.constrains('teaching_weeks')
    def _check_weeks(self):
        for rec in self:
            if not 1 <= rec.teaching_weeks <= 60:
                raise ValidationError(_("Teaching weeks must be between 1 and 60."))

    # ------------------------------------------------------------------ who may do what
    def _check_approver(self):
        if not is_approver(self.env):
            raise AccessError(_("Only the principal or an administrator can publish, archive or reopen a curriculum."))

    def _check_editable(self):
        """Draft: teachers may edit. Published / archived: principal / admin only."""
        if any(rec.state != 'draft' for rec in self) and not is_approver(self.env):
            raise AccessError(_("This curriculum is published. Only the principal or an administrator can change it."))

    def write(self, vals):
        if set(vals) - {'state', 'approved_by', 'approved_datetime'}:
            self._check_editable()
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()

    # ------------------------------------------------------------------ workflow buttons
    def action_publish(self):
        self._check_approver()
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.class_id:
                raise UserError(_("Add at least one topic row in the Subjects tab and choose its Class first."))
            if not rec.line_ids:
                raise UserError(_("Add at least one subject before publishing."))
            clash = self.search([('id', '!=', rec.id), ('state', 'in', ('published', 'done')),
                                 ('company_id', '=', rec.company_id.id),
                                 ('academic_year_id', '=', rec.academic_year_id.id),
                                 ('class_id', '=', rec.class_id.id)], limit=1)
            if clash:
                raise UserError(_(
                    "'%(name)s' is already published for %(cls)s in %(year)s. Archive it first.",
                    name=clash.name, cls=rec.class_id.name, year=rec.academic_year_id.name))
            rec.sudo().write({'state': 'published', 'approved_by': self.env.user.id,
                              'approved_datetime': fields.Datetime.now()})
            rec._notify_teachers(rec.line_ids)

    def _notify_teachers(self, lines):
        """Tell every subject teacher (that has an Odoo user) what she / he is assigned.
        The message arrives in the Inbox (bell icon) of the teacher."""
        self.ensure_one()
        by_user = {}
        for line in lines:
            user = line.teacher_user_id
            if user:
                by_user.setdefault(user, self.env['school.curriculum.line'])
                by_user[user] |= line
        for user, user_lines in by_user.items():
            rows = Markup('').join(
                Markup('<li><b>%s</b> - %g periods per week (%s annual)</li>') % (
                    l.subject_id.name, l.periods_per_week, l.total_periods) for l in user_lines)
            self.sudo().message_post(
                body=Markup(_("<p>You are the subject teacher in <b>%(name)s</b> (%(cls)s, %(year)s):</p><ul>%(rows)s</ul>")) % {
                    'name': self.name, 'cls': self.class_id.name, 'year': self.academic_year_id.name, 'rows': rows},
                subject=_("Curriculum assigned: %s", self.name),
                partner_ids=user.partner_id.ids, message_type='notification',
                subtype_xmlid='mail.mt_comment')

    def action_archive_curriculum(self):
        self._check_approver()
        self.sudo().write({'state': 'archived'})

    def action_set_draft(self):
        self._check_approver()
        self.sudo().write({'state': 'draft', 'approved_by': False, 'approved_datetime': False})

    def action_open_copy_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Copy to Another Academic Year'),
            'res_model': 'school.curriculum.copy.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_curriculum_id': self.id},
        }

    def _copy_to_year(self, year):
        """New DRAFT curriculum for another academic year, with all subject lines."""
        self.ensure_one()
        if year == self.academic_year_id:
            raise UserError(_("Choose a different academic year."))
        return self.create({
            'name': _("%(cls)s - %(year)s Curriculum", cls=self.class_id.name, year=year.name),
            'company_id': self.company_id.id, 'academic_year_id': year.id, 'class_id': self.class_id.id,
            'teaching_weeks': self.teaching_weeks, 'description': self.description,
            'teacher_id': self.teacher_id.id,
            'plan_ids': [(0, 0, {                   # the topics are planned again: the dates belong to the old year
                'sequence': p.sequence, 'class_id': p.class_id.id, 'section_id': p.section_id.id, 'subject_id': p.subject_id.id,
                'topic': p.topic, 'description': p.description}) for p in self.plan_ids],
            'line_ids': [(0, 0, {
                'sequence': l.sequence, 'subject_id': l.subject_id.id, 'subject_type': l.subject_type,
                'periods_per_week': l.periods_per_week, 'total_periods': l.total_periods,
                'teacher_id': l.teacher_id.id, 'notes': l.notes}) for l in self.line_ids],
        })


class SchoolCurriculumLine(models.Model):
    _name = 'school.curriculum.line'
    _description = 'Curriculum subject line'
    _order = 'curriculum_id, sequence, id'

    curriculum_id = fields.Many2one('school.curriculum', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    class_id = fields.Many2one(related='curriculum_id.class_id', store=True, string='Class')
    academic_year_id = fields.Many2one(related='curriculum_id.academic_year_id', store=True, string='Academic Year')
    curriculum_state = fields.Selection(related='curriculum_id.state', store=True, string='Curriculum Status')
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    subject_type = fields.Selection(
        [('core', 'Core'), ('elective', 'Elective'), ('co_scholastic', 'Co-scholastic / Activity')],
        string='Type', default='core', required=True)
    periods_per_week = fields.Float(string='Periods / Week', default=5.0)
    total_periods = fields.Integer(
        string='Annual Periods', compute='_compute_total_periods', store=True, readonly=False,
        help="Periods per week x teaching weeks. You can type another number.")
    teacher_id = fields.Many2one('school.teacher', string='Subject Teacher')
    teacher_user_id = fields.Many2one(
        'res.users', related='teacher_id.user_id', store=True, string='Teacher Login',
        help="The Odoo user of the subject teacher (used for 'My Subjects' and notifications).")
    notes = fields.Char(string='Notes')

    _curriculum_subject_uniq = models.Constraint(
        'UNIQUE(curriculum_id, subject_id)', 'This subject is already in the curriculum!')

    @api.depends('subject_id.name', 'curriculum_id.name')
    def _compute_display_name(self):
        for line in self:
            line.display_name = '%s (%s)' % (line.subject_id.name or '', line.curriculum_id.name or '')

    @api.depends('periods_per_week', 'curriculum_id.teaching_weeks')
    def _compute_total_periods(self):
        for line in self:
            line.total_periods = round(line.periods_per_week * (line.curriculum_id.teaching_weeks or 0))

    @api.constrains('periods_per_week', 'total_periods')
    def _check_periods(self):
        for line in self:
            if line.periods_per_week < 0 or line.total_periods < 0:
                raise ValidationError(_("Periods cannot be negative."))

    @api.constrains('subject_id', 'curriculum_id')
    def _check_subject_in_class(self):
        for line in self:
            classes = line.subject_id.class_ids
            if classes and line.curriculum_id.class_id and line.curriculum_id.class_id not in classes:
                raise ValidationError(_(
                    "Subject '%(subject)s' is not taught in %(cls)s.",
                    subject=line.subject_id.name, cls=line.curriculum_id.class_id.name))

    # a published curriculum is locked for teachers (lines included)
    @api.model_create_multi
    def create(self, vals_list):
        self.env['school.curriculum'].browse([v['curriculum_id'] for v in vals_list if v.get('curriculum_id')])._check_editable()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped('curriculum_id')._check_editable()
        old = {l.id: l.teacher_id for l in self} if 'teacher_id' in vals else {}
        res = super().write(vals)
        if old:
            for line in self.filtered(lambda l: l.curriculum_id.state in ('published', 'done')
                                      and l.teacher_id and l.teacher_id != old[l.id]):
                line.curriculum_id._notify_teachers(line)
        return res

    def unlink(self):
        self.mapped('curriculum_id')._check_editable()
        return super().unlink()


class SchoolCurriculumPlan(models.Model):
    """One topic of the curriculum with its section and start / end dates (the topic plan)."""
    _name = 'school.curriculum.plan'
    _description = 'Curriculum topic plan'
    _order = 'curriculum_id, date_start, sequence, id'

    curriculum_id = fields.Many2one('school.curriculum', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    class_id = fields.Many2one(
        'school.class', string='Class', required=True, index=True,
        default=lambda self: self.env.context.get('default_class_id'),
        help="The first topic row decides the class of the curriculum; every other row must have the same class.")
    academic_year_id = fields.Many2one(related='curriculum_id.academic_year_id', store=True, string='Academic Year')
    curriculum_state = fields.Selection(related='curriculum_id.state', store=True, string='Curriculum Status')
    section_id = fields.Many2one('school.section', string='Section', domain="[('class_id', '=', class_id)]",
                                 help="Leave empty when the topic is for every section of the class.")
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    topic = fields.Char(string='Topic', required=True)
    description = fields.Text(string='Description')
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    status = fields.Selection(
        [('pending', 'Pending'), ('in_progress', 'In Progress'), ('completed', 'Completed')],
        string='Status', default='pending', required=True, index=True,
        help="Set by the teacher while teaching. When every topic is Completed the curriculum becomes Done.")

    @api.depends('topic', 'subject_id.name')
    def _compute_display_name(self):
        for plan in self:
            plan.display_name = '%s (%s)' % (plan.topic or '', plan.subject_id.name or '')

    @api.constrains('date_start', 'date_end', 'curriculum_id')
    def _check_dates(self):
        for plan in self:
            if plan.date_start and plan.date_end and plan.date_end < plan.date_start:
                raise ValidationError(_("The end date of '%s' is before its start date.", plan.topic))
            year = plan.curriculum_id.academic_year_id
            for day in (plan.date_start, plan.date_end):
                if day and year.date_start and year.date_end and not (year.date_start <= day <= year.date_end):
                    raise ValidationError(_(
                        "'%(topic)s': %(day)s is outside the academic year %(year)s (%(start)s to %(end)s).",
                        topic=plan.topic, day=day, year=year.name, start=year.date_start, end=year.date_end))

    @api.constrains('class_id', 'curriculum_id')
    def _check_class(self):
        for plan in self:
            curriculum_class = plan.curriculum_id.class_id
            if curriculum_class and plan.class_id != curriculum_class:
                raise ValidationError(_(
                    "This curriculum is for %(cls)s, but the topic '%(topic)s' is for %(other)s. "
                    "Make another curriculum for %(other)s.",
                    cls=curriculum_class.name, topic=plan.topic, other=plan.class_id.name))

    @api.constrains('section_id', 'class_id')
    def _check_links(self):
        for plan in self:
            if plan.section_id and plan.section_id.class_id != plan.class_id:
                raise ValidationError(_("Section %(section)s is not a section of %(cls)s.",
                                        section=plan.section_id.name, cls=plan.class_id.name))

    def _sync_curriculum_class(self):
        """The class of the first topic row becomes the class of a curriculum that has none yet."""
        for plan in self:
            if not plan.curriculum_id.class_id:
                plan.curriculum_id.sudo().write({'class_id': plan.class_id.id})

    def _ensure_subject_lines(self):
        """A topic of a subject puts that subject in the 'Periods & Teachers' tab (0 periods, to be filled)."""
        Line = self.env['school.curriculum.line']
        for plan in self:
            curriculum = plan.curriculum_id
            if plan.subject_id not in curriculum.line_ids.mapped('subject_id'):
                Line.create({'curriculum_id': curriculum.id, 'subject_id': plan.subject_id.id,
                             'periods_per_week': 0.0})

    # the topic plan is part of the curriculum: same lock as the subject lines
    def _check_status_rights(self):
        """After publishing, only the status may change: by the curriculum teacher, the teacher of that
        subject, or the principal / admin."""
        if is_approver(self.env):
            return
        for plan in self:
            curriculum = plan.curriculum_id
            if curriculum.state == 'archived':
                raise AccessError(_("This curriculum is archived."))
            line = curriculum.line_ids.filtered(lambda l: l.subject_id == plan.subject_id)[:1]
            allowed = curriculum.sudo().teacher_user_id | line.sudo().teacher_user_id
            if self.env.user not in allowed:
                raise AccessError(_("Only the teacher of %(subject)s, the teacher who prepared this curriculum, "
                                    "or the principal can change the status.", subject=plan.subject_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        curricula = self.env['school.curriculum'].browse(
            [v['curriculum_id'] for v in vals_list if v.get('curriculum_id')])
        curricula._check_editable()
        for vals in vals_list:                                  # a row without a class takes the class of its curriculum
            if not vals.get('class_id') and vals.get('curriculum_id'):
                vals['class_id'] = self.env['school.curriculum'].browse(vals['curriculum_id']).class_id.id
        plans = super().create(vals_list)
        plans._sync_curriculum_class()
        plans._ensure_subject_lines()
        curricula._update_done_state()
        return plans

    def write(self, vals):
        curricula = self.mapped('curriculum_id')
        if vals and set(vals) <= {'status'} and all(c.state in ('published', 'done') for c in curricula):
            self._check_status_rights()                         # published: the teacher may only tick the status
        else:
            curricula._check_editable()
        res = super().write(vals)
        self._sync_curriculum_class()
        if 'subject_id' in vals or 'curriculum_id' in vals:
            self._ensure_subject_lines()
        curricula._update_done_state()
        return res

    def unlink(self):
        curricula = self.mapped('curriculum_id')
        curricula._check_editable()
        res = super().unlink()
        curricula._update_done_state()
        return res
