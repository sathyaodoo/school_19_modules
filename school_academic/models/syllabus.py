# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .curriculum import is_approver


class SchoolSyllabus(models.Model):
    """Syllabus of ONE subject for ONE class in ONE academic year."""
    _name = 'school.syllabus'
    _description = 'Syllabus (class + subject + academic year)'
    _inherit = ['mail.thread']
    _order = 'academic_year_id desc, class_id, subject_id, id desc'

    name = fields.Char(string='Syllabus Name', required=True)
    company_id = fields.Many2one('res.company', string='School / Board', required=True,
                                 default=lambda self: self.env.company)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one(
        'school.section', string='Section', index=True, domain="[('class_id', '=', class_id)]",
        help="Filled when the curriculum plans this subject for one section. Empty = the whole class.")
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    # what the curriculum offers (the form only lets you choose these)
    can_edit_structure = fields.Boolean(
        compute='_compute_can_edit_structure',
        help="Draft: teachers and the principal can type in the rows. After publishing: the principal / admin only.")
    allowed_class_ids = fields.Many2many('school.class', compute='_compute_allowed', string='Classes of the Curriculum')
    allowed_section_ids = fields.Many2many('school.section', compute='_compute_allowed', string='Sections of the Curriculum')
    allowed_subject_ids = fields.Many2many('school.subject', compute='_compute_allowed', string='Subjects of the Curriculum')
    state = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published'), ('archived', 'Archived')],
        string='Status', default='draft', required=True, index=True, tracking=True)

    # ---- link to the curriculum (periods allotted to this subject) ----
    curriculum_line_id = fields.Many2one(
        'school.curriculum.line', string='Curriculum Line', compute='_compute_curriculum_line',
        store=True, readonly=False, ondelete='set null',
        help="The subject line of the curriculum (same class, academic year and subject).")
    teacher_id = fields.Many2one(related='curriculum_line_id.teacher_id', string='Subject Teacher')
    teacher_user_id = fields.Many2one(related='curriculum_line_id.teacher_user_id', store=True, string='Teacher Login')
    allotted_periods = fields.Integer(compute='_compute_periods', string='Periods in Curriculum')
    planned_periods = fields.Integer(compute='_compute_periods', string='Planned in Units')
    balance_periods = fields.Integer(compute='_compute_periods', string='Balance')
    over_planned = fields.Boolean(compute='_compute_over_planned', store=True, string='More planned than allotted')
    unit_count = fields.Integer(compute='_compute_periods', string='Unit Count')
    topic_count = fields.Integer(compute='_compute_topic_count', string='Topic Count')
    progress = fields.Float(compute='_compute_progress', store=True, string='Progress %', aggregator='avg',
                            help="How much of the syllabus is taught. Units count in proportion to their planned periods.")

    # ---- content ----
    objectives = fields.Text(string='Objectives')
    reference_books = fields.Text(string='Textbooks & References')
    assessment_scheme = fields.Text(string='How it is assessed')
    attachment_ids = fields.Many2many(
        'ir.attachment', 'school_syllabus_attachment_rel', 'syllabus_id', 'attachment_id',
        string='Syllabus Documents (PDF / images)')
    unit_ids = fields.One2many('school.syllabus.unit', 'syllabus_id', string='Units')
    topic_ids = fields.One2many('school.syllabus.topic', 'syllabus_id', string='All Topics', readonly=True, copy=False)
    outcome_ids = fields.One2many('school.learning.outcome', 'syllabus_id', string='Learning Outcomes')
    outcome_count = fields.Integer(compute='_compute_outcome_count', string='Outcome Count')

    approved_by = fields.Many2one('res.users', string='Published By', readonly=True)
    approved_datetime = fields.Datetime(string='Published On', readonly=True)

    # ------------------------------------------------------------------ computes
    @api.depends('state')
    @api.depends_context('uid')
    def _compute_can_edit_structure(self):
        approver = is_approver(self.env)
        for rec in self:
            rec.can_edit_structure = rec.state == 'draft' or approver

    @api.depends('academic_year_id', 'company_id', 'class_id', 'subject_id')
    def _compute_allowed(self):
        """Classes, sections and subjects exactly as given in the (not archived) curricula of the year."""
        Curriculum = self.env['school.curriculum'].sudo()
        for rec in self:
            domain = [('state', '!=', 'archived'), ('company_id', '=', rec.company_id.id)]
            if rec.academic_year_id:
                domain.append(('academic_year_id', '=', rec.academic_year_id.id))
            curricula = Curriculum.search(domain)
            rec.allowed_class_ids = curricula.mapped('class_id')
            of_class = curricula.filtered(lambda c: c.class_id == rec.class_id) if rec.class_id else Curriculum
            rec.allowed_subject_ids = of_class.mapped('line_ids.subject_id')
            plans = of_class.mapped('plan_ids')
            if rec.subject_id:
                plans = plans.filtered(lambda p: p.subject_id == rec.subject_id)
            rec.allowed_section_ids = plans.mapped('section_id')

    @api.depends('class_id', 'academic_year_id', 'subject_id', 'company_id')
    def _compute_curriculum_line(self):
        Line = self.env['school.curriculum.line'].sudo()
        for rec in self:
            line = Line
            if rec.class_id and rec.academic_year_id and rec.subject_id:
                domain = [('class_id', '=', rec.class_id.id), ('academic_year_id', '=', rec.academic_year_id.id),
                          ('subject_id', '=', rec.subject_id.id), ('curriculum_id.company_id', '=', rec.company_id.id),
                          ('curriculum_state', '!=', 'archived')]
                # a published / done curriculum first, a draft only when there is nothing else
                line = (Line.search(domain + [('curriculum_state', 'in', ('published', 'done'))], order='id desc', limit=1)
                        or Line.search(domain, order='id desc', limit=1))
            rec.curriculum_line_id = line

    @api.depends('unit_ids.planned_periods', 'curriculum_line_id.total_periods')
    def _compute_periods(self):
        for rec in self:
            rec.unit_count = len(rec.unit_ids)
            rec.planned_periods = sum(rec.unit_ids.mapped('planned_periods'))
            rec.allotted_periods = rec.curriculum_line_id.total_periods
            rec.balance_periods = rec.allotted_periods - rec.planned_periods

    @api.depends('unit_ids.planned_periods', 'curriculum_line_id.total_periods')
    def _compute_over_planned(self):
        for rec in self:
            allotted = rec.curriculum_line_id.total_periods
            rec.over_planned = bool(allotted) and sum(rec.unit_ids.mapped('planned_periods')) > allotted

    def _compute_outcome_count(self):
        for rec in self:
            rec.outcome_count = len(rec.outcome_ids)

    def _compute_topic_count(self):
        Topic = self.env['school.syllabus.topic']
        for rec in self:
            rec.topic_count = Topic.search_count([('syllabus_id', '=', rec.id)]) if rec.id else 0

    @api.depends('unit_ids.progress', 'unit_ids.planned_periods')
    def _compute_progress(self):
        for rec in self:
            units = rec.unit_ids
            total = sum(units.mapped('planned_periods'))
            if not units:
                rec.progress = 0.0
            elif total:
                rec.progress = sum(u.progress * u.planned_periods for u in units) / total
            else:                                   # no periods given: every unit counts the same
                rec.progress = sum(units.mapped('progress')) / len(units)

    @api.onchange('class_id', 'academic_year_id', 'subject_id')
    def _onchange_suggest_name(self):
        if self.class_id and self.academic_year_id and self.subject_id and not self.name:
            self.name = _("%(subject)s - %(cls)s - %(year)s Syllabus", subject=self.subject_id.name,
                          cls=self.class_id.name, year=self.academic_year_id.name)

    def _active_duplicate(self):
        """Another syllabus (not archived) of the same school, year, class and subject."""
        self.ensure_one()
        return self.sudo().search([
            ('id', '!=', self.id), ('state', '!=', 'archived'), ('company_id', '=', self.company_id.id),
            ('academic_year_id', '=', self.academic_year_id.id), ('class_id', '=', self.class_id.id),
            ('section_id', '=', self.section_id.id or False), ('subject_id', '=', self.subject_id.id)], limit=1)

    @api.constrains('section_id', 'class_id')
    def _check_section_class(self):
        for rec in self:
            if rec.section_id and rec.section_id.class_id != rec.class_id:
                raise ValidationError(_("Section %(section)s is not a section of %(cls)s.",
                                        section=rec.section_id.name, cls=rec.class_id.name))

    @api.constrains('class_id', 'section_id', 'subject_id', 'academic_year_id', 'company_id')
    def _check_one_active_syllabus(self):
        """One syllabus per class + subject + year. Old duplicates are not touched until someone changes
        the class / subject / year of one of them, so they can still be cleaned up (archive / delete)."""
        for rec in self:
            if rec.state == 'archived':
                continue
            other = rec._active_duplicate()
            if other:
                raise ValidationError(_(
                    "A syllabus for %(subject)s - %(cls)s - %(year)s already exists for this section ('%(name)s', %(state)s). "
                    "Open that one instead, or archive it first.",
                    subject=rec.subject_id.name, cls=rec.class_id.name, year=rec.academic_year_id.name,
                    name=other.name, state=dict(other._fields['state'].selection)[other.state]))

    @api.constrains('subject_id', 'class_id')
    def _check_subject_in_class(self):
        for rec in self:
            if rec.subject_id.class_ids and rec.class_id not in rec.subject_id.class_ids:
                raise ValidationError(_("Subject '%(subject)s' is not taught in %(cls)s.",
                                        subject=rec.subject_id.name, cls=rec.class_id.name))

    # ------------------------------------------------------------------ rights
    def _check_approver(self):
        if not is_approver(self.env):
            raise AccessError(_("Only the principal or an administrator can publish, archive or reopen a syllabus."))

    def _check_progress_rights(self):
        """Who may tick topics as taught: any teacher while it is a draft; after publishing only the
        subject teacher (or the principal / admin)."""
        if is_approver(self.env):
            return
        for rec in self:
            if rec.state == 'draft':
                continue
            if rec.state == 'archived' or rec.teacher_user_id != self.env.user:
                raise AccessError(_("Only the subject teacher (%s) or the principal can update the progress.",
                                    rec.sudo().teacher_id.display_name or _("not assigned")))

    def _check_editable(self):
        if any(rec.state != 'draft' for rec in self) and not is_approver(self.env):
            raise AccessError(_("This syllabus is published. Only the principal or an administrator can change it."))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._link_files()
        return recs

    def write(self, vals):
        if set(vals) - {'state', 'approved_by', 'approved_datetime', 'curriculum_line_id'}:
            self._check_editable()
        res = super().write(vals)
        if 'attachment_ids' in vals:
            self._link_files()
        return res

    def unlink(self):
        self._check_editable()
        return super().unlink()

    def _link_files(self):
        """Uploaded files belong to this record, so every teacher can open them."""
        for rec in self:
            rec.attachment_ids.sudo().filtered(lambda a: not a.res_model).write(
                {'res_model': rec._name, 'res_id': rec.id})

    # ------------------------------------------------------------------ workflow
    def action_relink_curriculum(self):
        self._compute_curriculum_line()

    def action_publish(self):
        self._check_approver()
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.unit_ids:
                raise UserError(_("Add at least one unit before publishing."))
            clash = self.search([
                ('id', '!=', rec.id), ('state', '=', 'published'), ('company_id', '=', rec.company_id.id),
                ('academic_year_id', '=', rec.academic_year_id.id), ('class_id', '=', rec.class_id.id),
                ('section_id', '=', rec.section_id.id or False), ('subject_id', '=', rec.subject_id.id)], limit=1)
            if clash:
                raise UserError(_("'%s' is already published for this class, subject and year. Archive it first.",
                                  clash.name))
            rec._compute_curriculum_line()
            rec.sudo().write({'state': 'published', 'approved_by': self.env.user.id,
                              'approved_datetime': fields.Datetime.now()})

    def action_archive_syllabus(self):
        self._check_approver()
        self.sudo().write({'state': 'archived'})

    def action_set_draft(self):
        self._check_approver()
        for rec in self:
            if rec.state == 'archived':
                other = rec._active_duplicate()
                if other:
                    raise UserError(_("There is already an active syllabus for this class, subject and year ('%s'). "
                                      "Archive it before reopening this one.", other.name))
        self.sudo().write({'state': 'draft', 'approved_by': False, 'approved_datetime': False})

    def action_open_copy_wizard(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Copy to Another Academic Year'),
                'res_model': 'school.syllabus.copy.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_syllabus_id': self.id}}

    def _copy_to_year(self, year):
        self.ensure_one()
        if year == self.academic_year_id:
            raise UserError(_("Choose a different academic year."))
        new = self.create({
            'name': _("%(subject)s - %(cls)s - %(year)s Syllabus", subject=self.subject_id.name,
                      cls=self.class_id.name, year=year.name),
            'company_id': self.company_id.id, 'academic_year_id': year.id, 'class_id': self.class_id.id,
            'section_id': self.section_id.id, 'subject_id': self.subject_id.id, 'objectives': self.objectives,
            'reference_books': self.reference_books, 'assessment_scheme': self.assessment_scheme,
            'unit_ids': [(0, 0, {
                'sequence': u.sequence, 'name': u.name, 'description': u.description,
                'planned_periods': u.planned_periods,
                'topic_ids': [(0, 0, {'sequence': t.sequence, 'name': t.name, 'description': t.description,
                                      'planned_periods': t.planned_periods}) for t in u.topic_ids],   # progress starts again
            }) for u in self.unit_ids],
        })
        new._copy_outcomes_from(self)
        return new

    def _copy_outcomes_from(self, source):
        """Learning outcomes follow the syllabus to the next year (units / topics are matched by name)."""
        for outcome in source.outcome_ids:
            unit = self.unit_ids.filtered(lambda u: u.name == outcome.unit_id.name)[:1] if outcome.unit_id else False
            topic = self.topic_ids_by_name(outcome.topic_id.name, unit) if outcome.topic_id else False
            self.env['school.learning.outcome'].create({
                'syllabus_id': self.id, 'sequence': outcome.sequence, 'code': outcome.code, 'name': outcome.name,
                'description': outcome.description, 'bloom_level': outcome.bloom_level,
                'unit_id': unit.id if unit else False, 'topic_id': topic.id if topic else False})

    def topic_ids_by_name(self, name, unit):
        topics = (unit.topic_ids if unit else self.unit_ids.mapped('topic_ids'))
        return topics.filtered(lambda t: t.name == name)[:1]

    def _notify_teacher_to_prepare(self):
        """Tell the subject teacher that a syllabus draft is waiting for her / him."""
        for rec in self:
            user = rec.teacher_user_id
            if user:
                rec.sudo().message_post(
                    body=Markup(_("<p>Please prepare the syllabus of <b>%(subject)s</b> for %(cls)s, %(year)s "
                                  "(<b>%(periods)s</b> periods in the curriculum). Add the units and planned periods, "
                                  "then ask the principal to publish it.</p>")) % {
                        'subject': rec.subject_id.name, 'cls': rec.class_id.name,
                        'year': rec.academic_year_id.name, 'periods': rec.allotted_periods},
                    subject=_("Syllabus to prepare: %s", rec.name),
                    partner_ids=user.partner_id.ids, message_type='notification', subtype_xmlid='mail.mt_comment')


STATUS = [('not_started', 'Not Started'), ('in_progress', 'In Progress'), ('completed', 'Completed')]


class SchoolSyllabusUnit(models.Model):
    _name = 'school.syllabus.unit'
    _description = 'Syllabus unit'
    _order = 'syllabus_id, sequence, id'

    syllabus_id = fields.Many2one('school.syllabus', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Unit', required=True)
    description = fields.Text(string='What is covered')
    term_id = fields.Many2one('school.academic.term', string='Term')
    chapter_number = fields.Char(string='Chapter No.')
    chapter_name = fields.Char(string='Chapter Name')
    learning_objectives = fields.Text(string='Learning Objectives')
    teaching_materials = fields.Text(string='Teaching Materials')
    remarks = fields.Text(string='Remarks')
    planned_periods = fields.Integer(string='Planned Periods', default=0)
    topic_ids = fields.One2many('school.syllabus.topic', 'unit_id', string='Topics')
    topic_count = fields.Integer(compute='_compute_topics', string='Topic Count')
    topic_periods = fields.Integer(compute='_compute_topics', string='Periods in Topics')
    status = fields.Selection(
        STATUS, string='Status', compute='_compute_status', store=True, readonly=False,
        help="Calculated from the topics. A unit without topics can be set by hand.")
    progress = fields.Float(compute='_compute_progress', store=True, string='Progress %', aggregator='avg')
    class_id = fields.Many2one(related='syllabus_id.class_id', store=True, string='Class')
    subject_id = fields.Many2one(related='syllabus_id.subject_id', store=True, string='Subject')
    syllabus_state = fields.Selection(related='syllabus_id.state', store=True, string='Syllabus Status')

    @api.depends('topic_ids.planned_periods')
    def _compute_topics(self):
        for unit in self:
            unit.topic_count = len(unit.topic_ids)
            unit.topic_periods = sum(unit.topic_ids.mapped('planned_periods'))

    @api.depends('topic_ids.status')
    def _compute_status(self):
        for unit in self:
            if unit.topic_ids:
                states = set(unit.topic_ids.mapped('status'))
                unit.status = ('completed' if states == {'completed'}
                               else 'not_started' if states == {'not_started'} else 'in_progress')
            else:
                unit.status = unit.status or 'not_started'

    @api.depends('topic_ids.status', 'status')
    def _compute_progress(self):
        for unit in self:
            if unit.topic_ids:
                done = len(unit.topic_ids.filtered(lambda t: t.status == 'completed'))
                unit.progress = done * 100.0 / len(unit.topic_ids)
            else:
                unit.progress = 100.0 if unit.status == 'completed' else 0.0

    def action_open_unit_form(self):
        """The popup with the topics, periods and progress of this unit / chapter."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Unit / Chapter'), 'res_model': self._name,
                'res_id': self.id, 'view_mode': 'form', 'target': 'new',
                'views': [(self.env.ref('school_academic.view_school_syllabus_unit_form').id, 'form')]}

    @api.constrains('planned_periods')
    def _check_periods(self):
        for unit in self:
            if unit.planned_periods < 0:
                raise ValidationError(_("Planned periods cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        self.env['school.syllabus'].browse([v['syllabus_id'] for v in vals_list if v.get('syllabus_id')])._check_editable()
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) <= {'status', 'remarks'}:
            self.mapped('syllabus_id')._check_progress_rights()          # ticking a unit / writing a remark: the subject teacher
        else:
            self.mapped('syllabus_id')._check_editable()
        return super().write(vals)

    def unlink(self):
        self.mapped('syllabus_id')._check_editable()
        return super().unlink()


class SchoolSyllabusTopic(models.Model):
    """A topic taught inside a unit - the smallest thing the teacher ticks off."""
    _name = 'school.syllabus.topic'
    _description = 'Syllabus topic'
    _order = 'syllabus_id, unit_id, sequence, id'

    unit_id = fields.Many2one('school.syllabus.unit', string='Unit', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Topic', required=True)
    description = fields.Text(string='What is covered')
    planned_periods = fields.Integer(string='Planned Periods', default=0)
    status = fields.Selection(STATUS, string='Status', default='not_started', required=True, index=True)
    completed_date = fields.Date(string='Completed On')
    remarks = fields.Char(string='Teacher Remarks')
    completed_pct = fields.Float(compute='_compute_completed_pct', store=True, string='Completed %', aggregator='avg')

    syllabus_id = fields.Many2one(related='unit_id.syllabus_id', store=True, string='Syllabus', index=True)
    term_id = fields.Many2one(related='unit_id.term_id', store=True, string='Term')
    class_id = fields.Many2one(related='unit_id.syllabus_id.class_id', store=True, string='Class')
    subject_id = fields.Many2one(related='unit_id.syllabus_id.subject_id', store=True, string='Subject')
    academic_year_id = fields.Many2one(related='unit_id.syllabus_id.academic_year_id', store=True, string='Academic Year')
    syllabus_state = fields.Selection(related='unit_id.syllabus_id.state', store=True, string='Syllabus Status')
    teacher_user_id = fields.Many2one(related='unit_id.syllabus_id.teacher_user_id', store=True, string='Teacher Login')

    @api.depends('status')
    def _compute_completed_pct(self):
        for topic in self:
            topic.completed_pct = 100.0 if topic.status == 'completed' else 0.0

    @api.constrains('planned_periods')
    def _check_periods(self):
        for topic in self:
            if topic.planned_periods < 0:
                raise ValidationError(_("Planned periods cannot be negative."))

    def _syllabi(self):
        return self.mapped('unit_id.syllabus_id')

    @api.model_create_multi
    def create(self, vals_list):
        self.env['school.syllabus.unit'].browse([v['unit_id'] for v in vals_list if v.get('unit_id')]) \
            .mapped('syllabus_id')._check_editable()
        for vals in vals_list:
            if vals.get('status') == 'completed' and not vals.get('completed_date'):
                vals['completed_date'] = fields.Date.context_today(self)
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) <= {'status', 'completed_date', 'remarks'}:
            self._syllabi()._check_progress_rights()
            if 'status' in vals and 'completed_date' not in vals:
                vals = dict(vals, completed_date=fields.Date.context_today(self) if vals['status'] == 'completed' else False)
        else:
            self._syllabi()._check_editable()
        return super().write(vals)

    def unlink(self):
        self._syllabi()._check_editable()
        return super().unlink()

    # buttons used in the lists
    def action_mark_completed(self):
        self.write({'status': 'completed'})

    def action_mark_in_progress(self):
        self.write({'status': 'in_progress'})

    def action_reset_progress(self):
        self.write({'status': 'not_started'})
