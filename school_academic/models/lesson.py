# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .curriculum import approver_users, is_approver


def _default_teacher(env):
    return env['school.teacher'].sudo().search([('user_id', '=', env.uid)], limit=1)


class SchoolLessonPlan(models.Model):
    """A teacher's plan for one lesson (date + period) of one subject. Draft -> Submitted -> Approved."""
    _name = 'school.lesson.plan'
    _description = 'Lesson plan'
    _inherit = ['mail.thread']
    _order = 'planned_date desc, id desc'
    _rec_names_search = ['plan_code', 'name']

    plan_code = fields.Char(string='Plan ID', readonly=True, copy=False, index=True,
                            help="Assigned automatically when the plan is saved.")
    name = fields.Char(string='Lesson Title', help="Filled automatically (subject - planned date) when left empty.")
    class_id = fields.Many2one('school.class', string='Class', required=True, index=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True, index=True)
    company_id = fields.Many2one('res.company', string='School / Board', required=True,
                                 default=lambda self: self.env.company)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', compute='_compute_year',
                                       store=True, readonly=False)
    # found from class + subject + year (no longer chosen on the form); units / topics / outcomes come from it
    syllabus_id = fields.Many2one('school.syllabus', string='Syllabus', compute='_compute_syllabus',
                                  store=True, readonly=False, index=True, ondelete='set null')
    section_id = fields.Many2one('school.section', string='Section', domain="[('class_id', '=', class_id)]",
                                 help="Leave empty when the plan is for the whole class.")
    unit_id = fields.Many2one('school.syllabus.unit', string='Unit', domain="[('syllabus_id', '=', syllabus_id)]")
    topic_ids = fields.Many2many('school.syllabus.topic', 'school_lesson_topic_rel', 'plan_id', 'topic_id',
                                 string='Topics', domain="[('syllabus_id', '=', syllabus_id)]")
    outcome_ids = fields.Many2many('school.learning.outcome', 'school_lesson_outcome_rel', 'plan_id', 'outcome_id',
                                   string='Learning Outcomes', domain="[('syllabus_id', '=', syllabus_id)]")
    planned_date = fields.Date(string='Planned Date', required=True, default=fields.Date.context_today, tracking=True)
    completed_date = fields.Date(string='Completed Date', tracking=True, copy=False)
    progress = fields.Selection(
        [('planned', 'Planned'), ('in_progress', 'In Progress'), ('completed', 'Completed'),
         ('postponed', 'Postponed')],
        string='Lesson Status', default='planned', required=True, tracking=True, copy=False,
        help="How far the lesson is taught. Choosing Completed fills the Completed Date with today.")
    periods = fields.Integer(string='Periods', default=1)
    teacher_id = fields.Many2one('school.teacher', string='Teacher', default=lambda self: _default_teacher(self.env))
    teacher_user_id = fields.Many2one(related='teacher_id.user_id', store=True, string='Teacher Login')

    objectives = fields.Text(string='Lesson Objectives')
    activities = fields.Text(string='Teaching Activities', help="Introduction, explanation, activity, practice...")
    teaching_aids = fields.Text(string='Teaching Aids / Resources')
    assessment = fields.Text(string='How I will check learning')
    homework_plan = fields.Text(string='Homework Planned')
    attachment_ids = fields.Many2many('ir.attachment', 'school_lesson_attachment_rel', 'plan_id', 'attachment_id',
                                      string='Files (slides, worksheets)')

    state = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'), ('rejected', 'Rejected')],
        string='Status', default='draft', required=True, index=True, tracking=True, copy=False)
    reject_reason = fields.Text(string='Reason for Rejection', copy=False)
    submitted_datetime = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Decided By', readonly=True, copy=False)
    approved_datetime = fields.Datetime(string='Decided On', readonly=True, copy=False)

    diary_ids = fields.One2many('school.class.diary', 'lesson_plan_id', string='Diary Entries')
    diary_count = fields.Integer(compute='_compute_diary_count', string='Diary Count')

    _plan_code_uniq = models.Constraint('UNIQUE(plan_code)', 'This Plan ID is already used!')

    # ------------------------------------------------------------------ computes
    @api.depends('planned_date')
    def _compute_year(self):
        Year = self.env['school.academic.year'].sudo()
        for plan in self:
            plan.academic_year_id = Year.search(
                [('date_start', '<=', plan.planned_date), ('date_end', '>=', plan.planned_date)],
                order='date_start desc, id desc', limit=1) if plan.planned_date else False

    @api.depends('class_id', 'subject_id', 'academic_year_id', 'company_id', 'topic_ids')
    def _compute_syllabus(self):
        Syllabus = self.env['school.syllabus'].sudo()
        for plan in self:
            syllabus = plan.topic_ids[:1].sudo().syllabus_id
            if not syllabus and plan.class_id and plan.subject_id:
                domain = [('class_id', '=', plan.class_id.id), ('subject_id', '=', plan.subject_id.id),
                          ('state', '!=', 'archived')]
                if plan.company_id:
                    domain.append(('company_id', '=', plan.company_id.id))
                if plan.academic_year_id:
                    domain.append(('academic_year_id', '=', plan.academic_year_id.id))
                syllabus = Syllabus.search(domain + [('section_id', '=', False)], order='state desc, id desc', limit=1) \
                    or Syllabus.search(domain, order='state desc, id desc', limit=1)
            plan.syllabus_id = syllabus

    def _compute_diary_count(self):
        for plan in self:
            plan.diary_count = len(plan.diary_ids)

    # ------------------------------------------------------------------ checks
    @api.constrains('periods')
    def _check_periods(self):
        for plan in self:
            if plan.periods < 1:
                raise ValidationError(_("A lesson has at least one period."))

    @api.constrains('syllabus_id', 'unit_id', 'topic_ids', 'outcome_ids')
    def _check_syllabus_links(self):
        for plan in self:
            if plan.unit_id and plan.unit_id.syllabus_id != plan.syllabus_id:
                raise ValidationError(_("The unit does not belong to the syllabus of this lesson."))
            if plan.topic_ids.filtered(lambda t: t.syllabus_id != plan.syllabus_id):
                raise ValidationError(_("Every topic must be a topic of the syllabus of this lesson."))
            if plan.outcome_ids.filtered(lambda o: o.syllabus_id != plan.syllabus_id):
                raise ValidationError(_("Every learning outcome must belong to the syllabus of this lesson."))

    @api.onchange('class_id', 'subject_id')
    def _onchange_scope(self):
        if self.unit_id or self.topic_ids or self.outcome_ids:
            self.unit_id = self.topic_ids = self.outcome_ids = False

    @api.onchange('progress')
    def _onchange_progress(self):
        if self.progress == 'completed' and not self.completed_date:
            self.completed_date = fields.Date.context_today(self)

    @api.onchange('unit_id')
    def _onchange_unit(self):
        if self.unit_id:
            self.topic_ids = self.unit_id.topic_ids

    # ------------------------------------------------------------------ who may do what
    def _check_author(self):
        if is_approver(self.env):
            return
        for plan in self:
            if plan.teacher_user_id and plan.teacher_user_id != self.env.user:
                raise AccessError(_("Only %s (who wrote this lesson plan) can change it.", plan.sudo().teacher_id.display_name))

    def _check_approver(self):
        if not is_approver(self.env):
            raise AccessError(_("Only the principal or an administrator can approve or reject lesson plans."))

    def write(self, vals):
        workflow = {'state', 'reject_reason', 'submitted_datetime', 'approved_by', 'approved_datetime'}
        delivery = {'progress', 'completed_date'}        # the teacher updates these after approval too
        if set(vals) - workflow:
            self._check_author()
            if (set(vals) - workflow - delivery and any(p.state in ('submitted', 'approved') for p in self)
                    and not is_approver(self.env)):
                raise AccessError(_("A submitted or approved lesson plan is locked. Ask the principal to send it back."))
        if vals.get('progress') == 'completed' and 'completed_date' not in vals:
            no_date = self.filtered(lambda p: not p.completed_date)
            if no_date:                                   # keep a date that is already there
                super(SchoolLessonPlan, no_date).write({'completed_date': fields.Date.context_today(self)})
        res = super().write(vals)
        if 'attachment_ids' in vals:
            for plan in self:
                plan.attachment_ids.sudo().filtered(lambda a: not a.res_model).write(
                    {'res_model': plan._name, 'res_id': plan.id})
        return res

    @api.model_create_multi
    def create(self, vals_list):
        Sequence = self.env['ir.sequence']
        for vals in vals_list:
            if vals.get('syllabus_id'):                 # created from code with a syllabus: take its scope
                syllabus = self.env['school.syllabus'].sudo().browse(vals['syllabus_id'])
                vals.setdefault('class_id', syllabus.class_id.id)
                vals.setdefault('subject_id', syllabus.subject_id.id)
                vals.setdefault('company_id', syllabus.company_id.id)
                vals.setdefault('academic_year_id', syllabus.academic_year_id.id)
            if not vals.get('plan_code'):
                vals['plan_code'] = Sequence.next_by_code('school.lesson.plan')
            if not vals.get('name') and vals.get('subject_id'):
                subject = self.env['school.subject'].sudo().browse(vals['subject_id'])
                vals['name'] = '%s - %s' % (subject.name, vals.get('planned_date') or fields.Date.context_today(self))
            if vals.get('progress') == 'completed' and not vals.get('completed_date'):
                vals['completed_date'] = fields.Date.context_today(self)
        plans = super().create(vals_list)
        for plan in plans:
            plan.attachment_ids.sudo().filtered(lambda a: not a.res_model).write(
                {'res_model': plan._name, 'res_id': plan.id})
        return plans

    def unlink(self):
        self._check_author()
        if any(p.state in ('submitted', 'approved') for p in self) and not is_approver(self.env):
            raise AccessError(_("A submitted or approved lesson plan cannot be deleted."))
        return super().unlink()

    # ------------------------------------------------------------------ workflow
    def _notify(self, users, subject, body):
        for plan in self:
            partners = users.mapped('partner_id').ids
            if partners:
                plan.sudo().message_post(body=body, subject=subject, partner_ids=partners,
                                         message_type='notification', subtype_xmlid='mail.mt_comment')

    def action_submit(self):
        self._check_author()
        for plan in self:
            if plan.state not in ('draft', 'rejected'):
                continue
            plan.sudo().write({'state': 'submitted', 'submitted_datetime': fields.Datetime.now(),
                               'reject_reason': False, 'approved_by': False, 'approved_datetime': False})
            plan._notify(approver_users(self.env), _("Lesson plan to approve: %s", plan.name),
                         Markup(_("<p><b>%(teacher)s</b> submitted the lesson plan <b>%(name)s</b> "
                                  "(%(cls)s, %(subject)s, %(date)s).</p>")) % {
                             'teacher': plan.sudo().teacher_id.display_name or '', 'name': plan.name, 'cls': plan.class_id.name,
                             'subject': plan.subject_id.name, 'date': plan.planned_date})

    def action_approve(self):
        self._check_approver()
        for plan in self.filtered(lambda p: p.state == 'submitted'):
            plan.sudo().write({'state': 'approved', 'approved_by': self.env.user.id,
                               'approved_datetime': fields.Datetime.now(), 'reject_reason': False})
            plan._notify(plan.teacher_user_id, _("Lesson plan approved: %s", plan.name),
                         Markup(_("<p>Your lesson plan <b>%s</b> is approved.</p>")) % plan.name)

    def action_reject(self):
        self._check_approver()
        for plan in self:
            if plan.state != 'submitted':
                raise UserError(_("Only a submitted lesson plan can be rejected."))
            if not (plan.reject_reason or '').strip():
                raise UserError(_("Write the reason in 'Reason for Rejection' first."))
            plan.sudo().write({'state': 'rejected', 'approved_by': self.env.user.id,
                               'approved_datetime': fields.Datetime.now()})
            plan._notify(plan.teacher_user_id, _("Lesson plan needs changes: %s", plan.name),
                         Markup(_("<p>Your lesson plan <b>%(name)s</b> was sent back: %(reason)s</p>")) % {
                             'name': plan.name, 'reason': plan.reject_reason})

    def action_set_draft(self):
        """Author withdraws a submitted / rejected plan; the principal may reopen an approved one."""
        self._check_author()
        for plan in self:
            if plan.state == 'approved' and not is_approver(self.env):
                raise AccessError(_("Only the principal can reopen an approved lesson plan."))
            plan.sudo().write({'state': 'draft'})

    def action_create_diary(self):
        """Open a class diary entry pre-filled from this plan ('I taught this today')."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Class Diary'), 'res_model': 'school.class.diary',
            'view_mode': 'form', 'target': 'current',
            'context': {
                'default_lesson_plan_id': self.id, 'default_class_id': self.class_id.id,
                'default_section_id': self.section_id.id, 'default_subject_id': self.subject_id.id,
                'default_topic_ids': [(6, 0, self.topic_ids.ids)], 'default_outcome_ids': [(6, 0, self.outcome_ids.ids)],
                'default_summary': self.objectives, 'default_homework_text': self.homework_plan,
                'default_teacher_id': self.teacher_id.id},
        }

    def action_view_diary(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Class Diary'), 'res_model': 'school.class.diary',
                'view_mode': 'list,form', 'domain': [('lesson_plan_id', '=', self.id)]}
