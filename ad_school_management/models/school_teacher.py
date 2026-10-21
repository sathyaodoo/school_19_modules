from odoo import models, fields, api, _


def _float_to_hhmm(value):
    """9.5 -> '09:30'"""
    hours = int(value or 0)
    minutes = int(round(((value or 0) - hours) * 60))
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return '%02d:%02d' % (hours, minutes)


class SchoolTeacher(models.Model):
    _name = 'school.teacher'
    _description = 'Teacher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'hr.employee': 'employee_id'}

    employee_id = fields.Many2one('hr.employee', string='Employee Profile', required=True, ondelete='cascade')
    
    class_ids = fields.Many2many('school.class', 'school_class_teacher_rel', 'teacher_id', 'class_id', string='Assigned Classes')
    subject_ids = fields.Many2many('school.subject', 'school_subject_teacher_rel', 'teacher_id', 'subject_id', string='Assigned Subjects')
    class_teacher_class_ids = fields.One2many('school.class', 'class_teacher_id', string='Class Teacher For')
    class_teacher_section_ids = fields.One2many('school.section', 'class_teacher_id', string='Class Teacher Sections')
    class_teacher_for_text = fields.Char(string='Class Teacher For', compute='_compute_class_teacher_for_text')
    meal_entitled = fields.Boolean(
        string='Meal Entitled', default=False,
        help='Staff entitled to a canteen meal (used by the Canteen Daily Planning count)',
    )
  # --- My Timetable ---------------------------------------------------
    timetable_line_ids = fields.One2many('school.timetable.line', 'teacher_id', string='My Periods')
    weekly_period_count = fields.Integer(string='Periods per Week', compute='_compute_weekly_period_count')
    # In-app "timetable updated" alert (portal card + page)
    timetable_updated_on = fields.Datetime(string='Timetable Updated On', readonly=True, copy=False)
    timetable_seen_on = fields.Datetime(string='Timetable Seen On', readonly=True, copy=False)
    timetable_has_update = fields.Boolean(compute='_compute_timetable_has_update')


    @api.depends('class_teacher_section_ids.name', 'class_teacher_section_ids.class_id.name')
    def _compute_class_teacher_for_text(self):
        for teacher in self:
            teacher.class_teacher_for_text = ', '.join(
                '%s - %s' % (sec.class_id.name, sec.name) for sec in teacher.class_teacher_section_ids)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(SchoolTeacher, self).create(vals_list)
        for record in records:
            record.employee_id.write({'teacher_id': record.id})
        return records
    
    def write(self, vals):
        res = super().write(vals)
        if 'subject_ids' in vals:
            self.subject_ids._sync_teacher_classes()
        return res

    @api.depends('timetable_updated_on', 'timetable_seen_on')
    def _compute_timetable_has_update(self):
        for teacher in self:
            teacher.timetable_has_update = bool(teacher.timetable_updated_on) and (
                not teacher.timetable_seen_on or teacher.timetable_seen_on < teacher.timetable_updated_on)

    @api.depends('timetable_line_ids')
    def _compute_weekly_period_count(self):
        for teacher in self:
            teacher.weekly_period_count = len(teacher.timetable_line_ids)

    # ------------------------------------------------------------------
    # Weekly timetable (shared by the portal page and the notification)
    # ------------------------------------------------------------------
    def _school_timetable_lines(self):
        self.ensure_one()
        return self.env['school.timetable.line'].sudo().search(
            [('teacher_id', '=', self.id)], order='day_sequence, start_time, id')

    def _school_timetable_grid(self):
        """Weekly grid of this teacher's periods.

        Returns {'days': [(key, label)], 'rows': [{'label': '09:00 - 10:00',
        'cells': [[line, ...] per day]}], 'today': key, 'count': n}.
        Only days that have at least one period are shown (Saturday / Sunday
        appear only when used)."""
        self.ensure_one()
        Line = self.env['school.timetable.line']
        all_days = Line._fields['day_of_week']._description_selection(self.env)
        lines = self._school_timetable_lines()
        used = set(lines.mapped('day_of_week'))
        days = [(key, label) for key, label in all_days
                if key in used or key in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')]
        slots = sorted({(line.start_time, line.end_time) for line in lines})
        rows = []
        for start, end in slots:
            cells = []
            for day, _label in days:
                cells.append(lines.filtered(
                    lambda l, d=day, s=start, e=end: l.day_of_week == d and l.start_time == s and l.end_time == e))
            rows.append({'label': '%s - %s' % (_float_to_hhmm(start), _float_to_hhmm(end)), 'cells': cells})
        today = [key for key, _label in all_days][fields.Date.context_today(self).weekday()]
        return {'days': days, 'rows': rows, 'today': today, 'count': len(lines)}

    def _school_today_periods(self):
        self.ensure_one()
        today = self._school_timetable_grid()['today']
        return self._school_timetable_lines().filtered(lambda l: l.day_of_week == today)

    def _school_upcoming_substitutions(self, limit=20):
        """Periods this teacher has to cover for an absent colleague."""
        self.ensure_one()
        return self.env['school.substitution'].sudo().search([
            ('substitute_teacher_id', '=', self.id),
            ('state', '=', 'assigned'),
            ('date', '>=', fields.Date.context_today(self)),
        ], order='date, start_time', limit=limit)

    @api.model
    def _school_format_time(self, value):
        return _float_to_hhmm(value)

    # ------------------------------------------------------------------
    # Notification: "your timetable was updated" (in Odoo only, NO e-mail)
    # ------------------------------------------------------------------
    def _school_notify_timetable_updated(self):
        """Tell teachers their timetable changed, without any e-mail:

        * back-end teachers: a message in their Odoo inbox (bell), forced to
          the inbox even if their preference is "Handle by Emails", plus a
          live pop-up if they are online;
        * portal teachers: an "Updated" alert on their My Timetable card and
          page until they open it (timetable_updated_on / timetable_seen_on).
        """
        now = fields.Datetime.now()
        self.sudo().write({'timetable_updated_on': now})
        base_url = self and self[0].get_base_url() or ''
        for teacher in self:
            user = teacher.user_id
            if not user or user.share:
                continue  # portal teacher / no login: portal alert only
            body = self.env['ir.qweb']._render(
                'ad_school_management.teacher_timetable_notification_body', {
                    'teacher': teacher,
                    'grid': teacher._school_timetable_grid(),
                    'fmt': _float_to_hhmm,
                    'portal_url': base_url + '/odoo/action-ad_school_management.action_school_my_timetable',
                }, minimal_qcontext=True)
            teacher.sudo().with_context(school_timetable_inbox_only=True).message_notify(
                partner_ids=user.partner_id.ids,
                subject=_("Your timetable has been updated"),
                body=body,
                model_description=_('Timetable'),
            )
            self.env['bus.bus'].sudo()._sendone(user.partner_id, 'simple_notification', {
                'type': 'info',
                'title': _("Your timetable has been updated"),
                'message': _("You now have %s period(s) per week. Open My Timetable to see them.",
                             teacher.weekly_period_count),
                'sticky': True,
            })

    def _notify_get_recipients(self, message, msg_vals=False, **kwargs):
        """Timetable notifications never go out by e-mail: internal users get
        them in their Odoo inbox, everybody else is skipped (portal teachers
        see the alert on their portal page instead)."""
        recipients = super()._notify_get_recipients(message, msg_vals=msg_vals, **kwargs)
        if not self.env.context.get('school_timetable_inbox_only'):
            return recipients
        inbox_only = []
        for recipient in recipients:
            if recipient.get('uid') and not recipient.get('ushare'):
                inbox_only.append(dict(recipient, notif='inbox'))
        return inbox_only

    def _school_mark_timetable_seen(self):
        self.sudo().write({'timetable_seen_on': fields.Datetime.now()})

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------
    # Printing timetables is not required.
    # def action_print_timetable(self):
    #     # config=False: print straight away (never open the company
    #     # "Configure your document layout" wizard for a teacher).
    #     return self.env.ref('ad_school_management.action_report_teacher_timetable').report_action(self, config=False)
