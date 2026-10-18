from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


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
    total_hours = fields.Float(string='Total Hours', compute='_compute_sessions')
    outcome = fields.Text(string='Outcome')
    student_feedback = fields.Selection([
        ('1', 'Poor'), ('2', 'Fair'), ('3', 'Good'), ('4', 'Very Good'), ('5', 'Excellent'),
    ], string='Student Feedback')

    @api.depends('session_ids.duration')
    def _compute_sessions(self):
        for rec in self:
            rec.session_count = len(rec.session_ids)
            rec.total_hours = sum(rec.session_ids.mapped('duration'))

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

    @api.constrains('duration')
    def _check_duration(self):
        if any(rec.duration < 0 for rec in self):
            raise ValidationError(_("The duration cannot be negative."))