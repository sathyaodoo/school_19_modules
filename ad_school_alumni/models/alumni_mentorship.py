from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date


class SchoolAlumniMentorship(models.Model):
    """An alumni MENTOR guiding a current STUDENT."""
    _name = 'school.alumni.mentorship'
    _description = 'Alumni Mentorship'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')
    mentor_id = fields.Many2one('school.alumni', string='Mentor', required=True, tracking=True,
                                domain="[('stage', '=', 'mentor')]", index=True)
    mentor_expertise_ids = fields.Many2many(related='mentor_id.expertise_ids', string='Mentor Expertise')
    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True, index=True,
                                 domain="[('student_status', '!=', 'alumni')]")
    class_id = fields.Many2one(related='student_id.class_id', store=True, string='Class')
    section_id = fields.Many2one(related='student_id.section_id', store=True, string='Section')
    area = fields.Selection([
        ('career', 'Career Planning'),
        ('higher_studies', 'Higher Studies'),
        ('academics', 'Academics'),
        ('competitive_exams', 'Competitive Exams'),
        ('skills', 'Skills Development'),
        ('entrepreneurship', 'Entrepreneurship'),
        ('personal', 'Personal Growth'),
        ('other', 'Other'),
    ], string='Mentoring Area', required=True, default='career', tracking=True)
    expertise_id = fields.Many2one('school.alumni.expertise', string='Focus Expertise',
                                   domain="[('id', 'in', mentor_expertise_ids)]")
    goals = fields.Text(string='Goals')
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today, required=True)
    end_date = fields.Date(string='End Date')
    coordinator_id = fields.Many2one('res.users', string='Coordinator', default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, group_expand=True)
    session_ids = fields.One2many('school.alumni.mentorship.session', 'mentorship_id', string='Sessions')
    session_count = fields.Integer(compute='_compute_sessions')
    completed_session_count = fields.Integer(string='Completed Sessions', compute='_compute_sessions')
    planned_session_count = fields.Integer(string='Still Planned', compute='_compute_sessions')
    total_hours = fields.Float(string='Total Hours', compute='_compute_sessions',
                               help="Hours of completed sessions only.")
    can_complete = fields.Boolean(compute='_compute_sessions')
    outcome = fields.Text(string='Outcome')
    student_feedback = fields.Selection([
        ('1', 'Poor'), ('2', 'Fair'), ('3', 'Good'), ('4', 'Very Good'), ('5', 'Excellent'),
    ], string='Student Feedback')

    @api.depends('state', 'session_ids.duration', 'session_ids.state')
    def _compute_sessions(self):
        for rec in self:
            done = rec.session_ids.filtered(lambda s: s.state == 'completed')
            planned = rec.session_ids.filtered(lambda s: s.state == 'planned')
            rec.session_count = len(rec.session_ids)
            rec.completed_session_count = len(done)
            rec.planned_session_count = len(planned)
            rec.total_hours = sum(done.mapped('duration'))
            rec.can_complete = rec.state == 'active' and bool(done) and not planned

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.alumni.mentorship') or '/'
        return super().create(vals_list)

    @api.depends('name', 'mentor_id', 'student_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s: %s → %s' % (rec.name or '', rec.mentor_id.name or '',
                                                rec.student_id.name or '')

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_("The end date cannot be before the start date."))
        # the sessions must stay inside the (new) period
        self.session_ids._check_session_in_period()

    @api.constrains('mentor_id', 'student_id', 'state')
    def _check_unique_active(self):
        for rec in self.filtered(lambda r: r.state in ('draft', 'active')):
            dup = self.search_count([
                ('id', '!=', rec.id), ('mentor_id', '=', rec.mentor_id.id),
                ('student_id', '=', rec.student_id.id), ('state', 'in', ('draft', 'active')),
            ])
            if dup:
                raise ValidationError(_("%(mentor)s already has an open mentorship with %(student)s.",
                                        mentor=rec.mentor_id.name, student=rec.student_id.name))

    def action_start(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only a Draft mentorship can be started."))
            mentor = rec.mentor_id
            if mentor.stage != 'mentor':
                raise UserError(_("%s is not a Mentor yet. Make them a mentor on their alumni profile first.",
                                  mentor.name))
            if not mentor.mentor_available:
                raise UserError(_("%s is currently not available to mentor.", mentor.name))
            if mentor.max_mentees and mentor.active_mentee_count >= mentor.max_mentees:
                raise UserError(_("%(mentor)s already has %(count)s active mentee(s), the maximum set on "
                                  "their profile.", mentor=mentor.name, count=mentor.active_mentee_count))
        self.write({'state': 'active'})

    def action_complete(self):
        if any(rec.state != 'active' for rec in self):
            raise UserError(_("Only an Active mentorship can be completed."))
        for rec in self:
            if not rec.session_ids:
                raise UserError(_("%s: no sessions logged yet. Log and complete at least one session "
                                  "before completing the mentorship.", rec.name))
            if not rec.completed_session_count:
                raise UserError(_("%s: at least one session must be completed before completing the "
                                  "mentorship.", rec.name))
            if rec.planned_session_count:
                raise UserError(_("%(name)s: %(count)s session(s) are still planned. Complete or cancel "
                                  "them first.", name=rec.name, count=rec.planned_session_count))
            rec.write({'state': 'completed', 'end_date': rec.end_date or fields.Date.context_today(rec)})

    def action_cancel(self):
        if any(rec.state == 'completed' for rec in self):
            raise UserError(_("A completed mentorship cannot be cancelled."))
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.filtered(lambda r: r.state == 'cancelled').write({'state': 'draft'})


class SchoolAlumniMentorshipSession(models.Model):
    _name = 'school.alumni.mentorship.session'
    _description = 'Mentorship Session'
    _order = 'date desc, id desc'

    mentorship_id = fields.Many2one('school.alumni.mentorship', string='Mentorship', required=True,
                                    ondelete='cascade', index=True)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    duration = fields.Float(string='Duration (hours)', default=1.0)
    mode = fields.Selection([('in_person', 'In Person'), ('online', 'Online'), ('phone', 'Phone')],
                            string='Mode', default='online', required=True)
    topic = fields.Char(string='Topic', required=True)
    notes = fields.Text(string='Notes')
    state = fields.Selection([
        ('planned', 'Planned'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='planned', required=True, copy=False)

    # fields that can no longer change once a session is completed (Notes stays editable)
    _COMPLETED_LOCKED_FIELDS = {'date', 'duration', 'topic', 'mode', 'mentorship_id'}

    @api.constrains('duration')
    def _check_duration(self):
        if any(rec.duration < 0 for rec in self):
            raise ValidationError(_("The duration cannot be negative."))

    @api.constrains('date', 'mentorship_id', 'state')
    def _check_session_in_period(self):
        for rec in self.filtered(lambda s: s.state != 'cancelled' and s.date):
            mentorship = rec.mentorship_id
            start, end = mentorship.start_date, mentorship.end_date
            if (start and rec.date < start) or (end and rec.date > end):
                raise ValidationError(_(
                    "Session on %(date)s is outside the mentorship period (%(start)s – %(end)s).",
                    date=format_date(self.env, rec.date),
                    start=format_date(self.env, start) if start else '…',
                    end=format_date(self.env, end) if end else _("open")))

    def write(self, vals):
        locked = self._COMPLETED_LOCKED_FIELDS.intersection(vals)
        if locked and any(rec.state == 'completed' for rec in self):
            raise UserError(_("A completed session's date, duration, topic and mode can't be changed. "
                              "Only its notes can be edited."))
        return super().write(vals)

    def unlink(self):
        if any(rec.state == 'completed' for rec in self):
            raise UserError(_("A completed session can't be deleted."))
        return super().unlink()

    def action_complete_session(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state != 'planned':
                raise UserError(_("Only a planned session can be completed."))
            if rec.mentorship_id.state != 'active':
                raise UserError(_("Sessions can only be completed while the mentorship is Active."))
            if rec.date > today:
                raise UserError(_("The session on %s is in the future and can't be completed yet.",
                                  format_date(self.env, rec.date)))
        self.write({'state': 'completed'})

    def action_cancel_session(self):
        for rec in self:
            if rec.state != 'planned':
                raise UserError(_("Only a planned session can be cancelled."))
            if rec.mentorship_id.state in ('completed', 'cancelled'):
                raise UserError(_("The mentorship is closed; its sessions can't be changed."))
        self.write({'state': 'cancelled'})

    def action_reset_planned(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_("Only a cancelled session can be reset to planned."))
            if rec.mentorship_id.state in ('completed', 'cancelled'):
                raise UserError(_("The mentorship is closed; its sessions can't be changed."))
        self.write({'state': 'planned'})