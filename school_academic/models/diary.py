# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .curriculum import is_approver
from .lesson import _default_teacher


class SchoolClassDiary(models.Model):
    """What was taught in one lesson of one class (and what homework was given)."""
    _name = 'school.class.diary'
    _description = 'Class diary entry'
    _order = 'date desc, class_id, period_no, id desc'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, index=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, index=True)
    section_id = fields.Many2one('school.section', string='Section', domain="[('class_id', '=', class_id)]",
                                 help="Leave empty when the entry is for every section of the class.")
    subject_id = fields.Many2one('school.subject', string='Subject', required=True, index=True)
    period_no = fields.Integer(string='Period No.')
    company_id = fields.Many2one('res.company', string='School / Board', required=True,
                                 default=lambda self: self.env.company)
    teacher_id = fields.Many2one('school.teacher', string='Teacher', default=lambda self: _default_teacher(self.env))
    teacher_user_id = fields.Many2one(related='teacher_id.user_id', store=True, string='Teacher Login')

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', compute='_compute_year',
                                       store=True, readonly=False)
    syllabus_id = fields.Many2one('school.syllabus', string='Syllabus', compute='_compute_syllabus',
                                  store=True, readonly=False, ondelete='set null')
    lesson_plan_id = fields.Many2one('school.lesson.plan', string='Lesson Plan', ondelete='set null',
                                     domain="[('class_id', '=', class_id), ('subject_id', '=', subject_id)]")
    topic_ids = fields.Many2many('school.syllabus.topic', 'school_diary_topic_rel', 'diary_id', 'topic_id',
                                 string='Topics Taught', domain="[('syllabus_id', '=', syllabus_id)]")
    outcome_ids = fields.Many2many('school.learning.outcome', 'school_diary_outcome_rel', 'diary_id', 'outcome_id',
                                   string='Learning Outcomes', domain="[('syllabus_id', '=', syllabus_id)]")
    mark_topics_done = fields.Boolean(
        string='Topics are finished', help="Tick when these topics are completely taught. They are then marked "
                                           "Completed in the syllabus. Otherwise they become 'In Progress'.")

    summary = fields.Text(string='What was taught')
    classwork = fields.Text(string='Classwork')
    homework_text = fields.Text(string='Homework (short note)')
    remarks = fields.Text(string='Note for Parents')
    homework_ids = fields.One2many('school.oe.assignment', 'diary_id', string='Homework Assignments')
    homework_count = fields.Integer(compute='_compute_homework_count', string='Homework Count')

    state = fields.Selection([('draft', 'Draft'), ('published', 'Published')], string='Status',
                             default='draft', required=True, index=True)
    published_datetime = fields.Datetime(string='Published On', readonly=True)

    # ------------------------------------------------------------------ computes
    @api.depends('date')
    def _compute_year(self):
        Year = self.env['school.academic.year'].sudo()
        for diary in self:
            diary.academic_year_id = Year.search(
                [('date_start', '<=', diary.date), ('date_end', '>=', diary.date)],
                order='date_start desc, id desc', limit=1) if diary.date else False

    @api.depends('class_id', 'section_id', 'subject_id', 'academic_year_id', 'company_id', 'lesson_plan_id', 'topic_ids')
    def _compute_syllabus(self):
        Syllabus = self.env['school.syllabus'].sudo()
        for diary in self:
            # 1. the syllabus of the lesson plan, 2. the syllabus the chosen topics belong to, 3. best match
            syllabus = diary.lesson_plan_id.sudo().syllabus_id
            if not syllabus and diary.topic_ids:
                syllabus = diary.topic_ids[:1].sudo().syllabus_id
            if syllabus:
                diary.syllabus_id = syllabus
                continue
            syllabus = Syllabus
            if diary.class_id and diary.subject_id:
                domain = [('class_id', '=', diary.class_id.id), ('subject_id', '=', diary.subject_id.id),
                          ('company_id', '=', diary.company_id.id), ('state', '!=', 'archived')]
                if diary.academic_year_id:
                    domain.append(('academic_year_id', '=', diary.academic_year_id.id))
                order = 'state desc, id desc'
                syllabus = (diary.section_id and Syllabus.search(
                                domain + [('section_id', '=', diary.section_id.id)], order=order, limit=1)) \
                    or Syllabus.search(domain + [('section_id', '=', False)], order=order, limit=1) \
                    or Syllabus.search(domain, order=order, limit=1)
            diary.syllabus_id = syllabus

    def _compute_homework_count(self):
        for diary in self:
            diary.homework_count = len(diary.homework_ids)

    @api.depends('subject_id.name', 'class_id.name', 'date')
    def _compute_display_name(self):
        for diary in self:
            diary.display_name = '%s - %s - %s' % (diary.subject_id.name or '', diary.class_id.name or '', diary.date or '')

    # ------------------------------------------------------------------ checks
    @api.constrains('syllabus_id', 'topic_ids', 'outcome_ids', 'lesson_plan_id', 'class_id', 'subject_id')
    def _check_links(self):
        for diary in self:
            syllabus = diary.syllabus_id
            if syllabus and (syllabus.class_id != diary.class_id or syllabus.subject_id != diary.subject_id):
                raise ValidationError(_(
                    "The topics / lesson plan belong to %(sub)s of %(cls)s, but this diary entry is for %(dsub)s of %(dcls)s.",
                    sub=syllabus.subject_id.name, cls=syllabus.class_id.name,
                    dsub=diary.subject_id.name, dcls=diary.class_id.name))
            if diary.topic_ids.filtered(lambda t: t.syllabus_id != diary.syllabus_id):
                raise ValidationError(_("Every topic must be a topic of the syllabus of %(subject)s (%(cls)s).",
                                        subject=diary.subject_id.name, cls=diary.class_id.name))
            if diary.outcome_ids.filtered(lambda o: o.syllabus_id != diary.syllabus_id):
                raise ValidationError(_("Every learning outcome must belong to the syllabus of this subject and class."))
            plan = diary.lesson_plan_id
            if plan and (plan.class_id != diary.class_id or plan.subject_id != diary.subject_id):
                raise ValidationError(_("The lesson plan is for another class or subject."))

    @api.constrains('period_no')
    def _check_period(self):
        for diary in self:
            if diary.period_no < 0:
                raise ValidationError(_("Period number cannot be negative."))

    @api.onchange('class_id', 'subject_id', 'date')
    def _onchange_scope(self):
        if self.topic_ids or self.outcome_ids:
            self.topic_ids = self.outcome_ids = False

    @api.onchange('lesson_plan_id')
    def _onchange_lesson_plan(self):
        plan = self.lesson_plan_id
        if plan:
            self.topic_ids = plan.topic_ids
            self.outcome_ids = plan.outcome_ids
            self.summary = self.summary or plan.objectives
            self.homework_text = self.homework_text or plan.homework_plan

    # ------------------------------------------------------------------ rights
    def _check_author(self):
        if is_approver(self.env):
            return
        for diary in self:
            if diary.teacher_user_id and diary.teacher_user_id != self.env.user:
                raise AccessError(_("Only %s (who wrote this diary entry) can change it.", diary.sudo().teacher_id.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        diaries = super().create(vals_list)
        diaries._adopt_homework()
        return diaries

    def _adopt_homework(self):
        """Homework of the same class + subject (+ section) created on the day of this entry belongs to it."""
        Assignment = self.env['school.oe.assignment'].sudo()
        for diary in self:
            works = Assignment.search([
                ('kind', '=', 'homework'), ('diary_id', '=', False),
                ('class_id', '=', diary.class_id.id), ('subject_id', '=', diary.subject_id.id)])
            for work in works:
                created_day = fields.Datetime.context_timestamp(diary, work.create_date).date()
                if created_day != diary.date:
                    continue
                if diary.section_id and work.section_id and work.section_id != diary.section_id:
                    continue
                work.diary_id = diary

    def write(self, vals):
        if set(vals) - {'state', 'published_datetime'}:
            self._check_author()
        return super().write(vals)

    def unlink(self):
        self._check_author()
        return super().unlink()

    # ------------------------------------------------------------------ workflow
    def _update_topic_progress(self):
        """Publishing a diary entry moves the syllabus: topics become In Progress / Completed."""
        for diary in self:
            topics = diary.topic_ids
            if not topics:
                continue
            if diary.mark_topics_done:
                try:
                    topics.filtered(lambda t: t.status != 'completed').write({'status': 'completed'})
                except AccessError:
                    raise UserError(_("Only the subject teacher (%s) or the principal can mark topics as completed.",
                                      diary.syllabus_id.sudo().teacher_id.display_name or _("not assigned")))
            else:
                try:
                    topics.filtered(lambda t: t.status == 'not_started').write({'status': 'in_progress'})
                except AccessError:
                    pass                                    # not the subject teacher: the diary is still saved

    def action_publish(self):
        self._check_author()
        for diary in self:
            if diary.state == 'published':
                continue
            if not (diary.summary or diary.topic_ids):
                raise UserError(_("Write what was taught, or choose the topics, before publishing."))
            diary._update_topic_progress()
            diary.sudo().write({'state': 'published', 'published_datetime': fields.Datetime.now()})
            diary._adopt_homework()

    def action_unpublish(self):
        self._check_author()
        self.sudo().write({'state': 'draft', 'published_datetime': False})

    def action_give_homework(self):
        """Open a new Homework (an Online Exam assignment) linked to this diary entry."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Homework'), 'res_model': 'school.oe.assignment',
            'view_mode': 'form', 'target': 'current',
            'context': {
                'default_kind': 'homework', 'default_diary_id': self.id, 'default_class_id': self.class_id.id,
                'default_section_id': self.section_id.id, 'default_subject_id': self.subject_id.id,
                'default_name': _("Homework - %(subject)s - %(date)s", subject=self.subject_id.name, date=self.date),
                'default_instructions': self.homework_text, 'default_max_marks': 10.0,
                'default_due_datetime': fields.Datetime.now() + timedelta(days=1),
                'default_outcome_ids': [(6, 0, self.outcome_ids.ids)]},
        }

    def action_view_homework(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Homework'), 'res_model': 'school.oe.assignment',
                'view_mode': 'list,form', 'domain': [('diary_id', '=', self.id)]}
