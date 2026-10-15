from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def _float_to_time(value):
    hours = int(value)
    minutes = int(round((value - hours) * 60))
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return '%02d:%02d' % (hours, minutes)


class SchoolSubjectGroup(models.Model):
    """Subjects that are similar enough for a teacher of one to cover another,
    e.g. Science = Physics, Chemistry, Biology."""
    _name = 'school.subject.group'
    _description = 'Subject Group'
    _order = 'name'

    name = fields.Char(string='Subject Group', required=True)
    subject_ids = fields.One2many('school.subject', 'subject_group_id', string='Subjects')
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This subject group already exists!')


class SchoolSubject(models.Model):
    _inherit = 'school.subject'

    subject_group_id = fields.Many2one(
        'school.subject.group', string='Subject Group',
        help='Teachers of subjects in the same group can substitute for each other.')


class SchoolSubstitution(models.Model):
    """One timetable period that needs a substitute because its teacher is on leave."""
    _name = 'school.substitution'
    _description = 'Teacher Substitution'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date, start_time, id'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(string='Date', required=True, tracking=True)
    timetable_line_id = fields.Many2one('school.timetable.line', string='Period', required=True,
                                        ondelete='cascade')
    leave_id = fields.Many2one('hr.leave', string='Leave', ondelete='set null', readonly=True)
    absent_teacher_id = fields.Many2one('school.teacher', string='Teacher on Leave', required=True,
                                        tracking=True)

    class_id = fields.Many2one(related='timetable_line_id.timetable_id.class_id', store=True, string='Class')
    section_id = fields.Many2one(related='timetable_line_id.timetable_id.section_id', store=True, string='Section')
    subject_id = fields.Many2one(related='timetable_line_id.subject_id', store=True, string='Subject')
    subject_group_id = fields.Many2one(related='timetable_line_id.subject_id.subject_group_id',
                                       string='Subject Group')
    classroom = fields.Char(related='timetable_line_id.classroom', store=True, string='Classroom')
    start_time = fields.Float(related='timetable_line_id.start_time', store=True, string='Start')
    end_time = fields.Float(related='timetable_line_id.end_time', store=True, string='End')
    period_label = fields.Char(compute='_compute_period_label', string='Time')

    available_teacher_ids = fields.Many2many(
        'school.teacher', compute='_compute_available_teachers', string='Available Substitutes',
        help='Free at this time, not on leave, and teaching the same or a similar subject '
             '(same subject first).')
    available_count = fields.Integer(compute='_compute_available_teachers', string='No. Available')
    substitute_teacher_id = fields.Many2one(
        'school.teacher', string='Substitute Teacher', tracking=True,
        domain="[('id', 'in', available_teacher_ids)]")
    substitute_match = fields.Selection(
        [('same', 'Same Subject'), ('similar', 'Similar Subject')],
        compute='_compute_substitute_match', string='Match')
    state = fields.Selection(
        [('draft', 'To Assign'), ('assigned', 'Assigned'), ('cancel', 'Cancelled')],
        string='Status', default='draft', required=True, tracking=True)
    notified_date = fields.Datetime(string='Email Sent On', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)

    _period_date_uniq = models.Constraint(
        'unique(timetable_line_id, date)', 'A substitution already exists for this period on this date!'
    )

    # ------------------------------------------------------------------
    @api.depends('start_time', 'end_time')
    def _compute_period_label(self):
        for sub in self:
            sub.period_label = '%s – %s' % (_float_to_time(sub.start_time), _float_to_time(sub.end_time))

    @api.depends('date', 'timetable_line_id', 'subject_id', 'class_id', 'section_id', 'start_time', 'end_time')
    def _compute_name(self):
        for sub in self:
            sub.name = '%s %s – %s | %s %s | %s' % (
                sub.date or '', _float_to_time(sub.start_time), _float_to_time(sub.end_time),
                sub.class_id.name or '', sub.section_id.name or '', sub.subject_id.name or '')

    @api.depends('date', 'timetable_line_id', 'absent_teacher_id', 'state')
    def _compute_available_teachers(self):
        for sub in self:
            teachers = sub._get_available_teachers() if sub.date and sub.timetable_line_id else \
                self.env['school.teacher']
            sub.available_teacher_ids = teachers
            sub.available_count = len(teachers)

    @api.depends('substitute_teacher_id', 'subject_id')
    def _compute_substitute_match(self):
        for sub in self:
            teacher = sub.substitute_teacher_id
            if not teacher:
                sub.substitute_match = False
            elif sub.subject_id in teacher.subject_ids:
                sub.substitute_match = 'same'
            else:
                sub.substitute_match = 'similar'

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    def _get_available_teachers(self):
        """Teachers who can cover this period, same subject first.

        A teacher is available when they:
          * teach the same subject, or a subject of the same Subject Group,
          * are not the teacher on leave,
          * have no approved leave on that date,
          * have no own class overlapping this period on that weekday,
          * are not already substituting another class at that time.
        """
        self.ensure_one()
        Teacher = self.env['school.teacher']
        subject = self.subject_id
        same = Teacher.search([('subject_ids', 'in', subject.id)])
        similar = Teacher.browse()
        if subject.subject_group_id:
            similar = Teacher.search([
                ('subject_ids.subject_group_id', '=', subject.subject_group_id.id),
            ]) - same
        candidates = (same | similar) - self.absent_teacher_id
        if not candidates:
            return Teacher

        # On approved leave that day
        on_leave = self.env['hr.leave'].sudo().search([
            ('employee_id', 'in', candidates.employee_id.ids),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', self.date),
            ('request_date_to', '>=', self.date),
        ]).employee_id
        candidates = candidates.filtered(lambda t: t.employee_id not in on_leave)

        # Own class at the same time
        weekday = WEEKDAYS[self.date.weekday()]
        busy_lines = self.env['school.timetable.line'].sudo().search([
            ('teacher_id', 'in', candidates.ids),
            ('day_of_week', '=', weekday),
            ('start_time', '<', self.end_time),
            ('end_time', '>', self.start_time),
            ('timetable_id.academic_year_id.date_start', '<=', self.date),
            ('timetable_id.academic_year_id.date_end', '>=', self.date),
        ])
        # Already substituting elsewhere at the same time
        busy_subs = self.sudo().search([
            ('id', '!=', self._origin.id or 0),
            ('date', '=', self.date),
            ('state', '=', 'assigned'),
            ('substitute_teacher_id', 'in', candidates.ids),
            ('start_time', '<', self.end_time),
            ('end_time', '>', self.start_time),
        ])
        busy = busy_lines.teacher_id | busy_subs.substitute_teacher_id
        candidates -= busy
        # Same subject first, then similar; alphabetical inside each
        return candidates.sorted(lambda t: (subject not in t.subject_ids, t.name or ''))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_assign(self):
        """Confirm the chosen substitute and email them immediately."""
        template = self.env.ref('ad_school_management.email_template_teacher_substitution',
                                raise_if_not_found=False)
        for sub in self:
            if sub.state == 'cancel':
                raise UserError(_("This substitution is cancelled."))
            if not sub.substitute_teacher_id:
                raise UserError(_("Please select a Substitute Teacher first."))
            if sub.substitute_teacher_id not in sub._get_available_teachers():
                raise ValidationError(_(
                    "%(teacher)s is not available for this period: they must teach %(subject)s or a "
                    "similar subject, and be free and not on leave at that time.",
                    teacher=sub.substitute_teacher_id.name, subject=sub.subject_id.name))
            sub.state = 'assigned'
            email = sub.substitute_teacher_id.work_email
            if template and email:
                # force_send=True -> sent right now, not left in the outgoing queue
                mail_id = template.send_mail(sub.id, force_send=True, raise_exception=False)
                mail = self.env['mail.mail'].sudo().browse(mail_id).exists()
                if mail and mail.state == 'sent':
                    sub.notified_date = fields.Datetime.now()
                    sub.message_post(body=_("Substitution email sent to %(name)s (%(email)s).",
                                            name=sub.substitute_teacher_id.name, email=email))
                else:
                    reason = (mail.failure_reason if mail else '') or _("unknown error")
                    sub.message_post(body=_(
                        "Substitution email to %(name)s (%(email)s) could not be sent: %(reason)s. "
                        "It stays in the outgoing queue and will be retried.",
                        name=sub.substitute_teacher_id.name, email=email, reason=reason))
            else:
                sub.message_post(body=_(
                    "%s has no work email, so no notification was sent. "
                    "Please inform them directly.", sub.substitute_teacher_id.name))
        return True

    def action_reset(self):
        self.write({'state': 'draft', 'substitute_teacher_id': False, 'notified_date': False})
        return True

    def action_cancel(self):
        self.write({'state': 'cancel'})
        return True

    # ------------------------------------------------------------------
    # Generation from leave
    # ------------------------------------------------------------------
    @api.model
    def _generate_for_leave(self, leave):
        """Create one substitution per timetable period the teacher misses."""
        teacher = leave.employee_id.teacher_id
        if not teacher:
            return self.browse()
        start = leave.request_date_from or leave.date_from.date()
        end = leave.request_date_to or leave.date_to.date()
        Line = self.env['school.timetable.line'].sudo()
        vals_list = []
        day = start
        while day <= end:
            lines = Line.search([
                ('teacher_id', '=', teacher.id),
                ('day_of_week', '=', WEEKDAYS[day.weekday()]),
                ('timetable_id.academic_year_id.date_start', '<=', day),
                ('timetable_id.academic_year_id.date_end', '>=', day),
            ])
            existing = self.sudo().search([('date', '=', day), ('timetable_line_id', 'in', lines.ids)])
            for line in lines - existing.timetable_line_id:
                vals_list.append({
                    'date': day,
                    'timetable_line_id': line.id,
                    'absent_teacher_id': teacher.id,
                    'leave_id': leave.id,
                })
            # A cancelled substitution for the same period comes back to "To Assign"
            existing.filtered(lambda s: s.state == 'cancel').write(
                {'state': 'draft', 'leave_id': leave.id, 'substitute_teacher_id': False})
            day += timedelta(days=1)
        return self.sudo().create(vals_list)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    school_substitution_ids = fields.One2many('school.substitution', 'leave_id', string='Substitutions')
    school_substitution_count = fields.Integer(compute='_compute_school_substitution_count')

    def _compute_school_substitution_count(self):
        counts = dict(self.env['school.substitution'].sudo()._read_group(
            [('leave_id', 'in', self.ids)], ['leave_id'], ['__count']))
        for leave in self:
            leave.school_substitution_count = counts.get(leave, 0)

    def write(self, vals):
        previous = {leave.id: leave.state for leave in self}
        res = super().write(vals)
        if 'state' in vals:
            Substitution = self.env['school.substitution'].sudo()
            for leave in self:
                if leave.state == 'validate' and previous.get(leave.id) != 'validate':
                    Substitution._generate_for_leave(leave)
                elif leave.state in ('refuse', 'cancel') and previous.get(leave.id) == 'validate':
                    leave.sudo().school_substitution_ids.filtered(
                        lambda s: s.state != 'cancel').write({'state': 'cancel'})
        return res

    def action_view_school_substitutions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Substitutions'),
            'res_model': 'school.substitution',
            'view_mode': 'list,form',
            'domain': [('leave_id', '=', self.id)],
        }