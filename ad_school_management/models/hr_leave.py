from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date

SCHOOL_LEVEL_GROUPS = {
    'admin': 'ad_school_management.group_school_admin',
    'hr': 'ad_school_management.group_school_hr_manager',
    'principal': 'ad_school_management.group_school_principal',
}
SCHOOL_LEVEL_LABELS = {
    'admin': 'Administration (1st level)',
    'hr': 'HR Manager (2nd level)',
    'principal': 'Principal (final approval)',
}


class HrLeave(models.Model):
    """School leave approval built on the STANDARD Time Off workflow.

    Standard states are kept untouched so allocations, balances, reports,
    calendars and overlap checks keep working. The three school levels are
    mapped onto the standard 'both' validation:

        state 'confirm'   (To Approve)       -> Admin approval (1st level)
        state 'validate1' (Second Approval)  -> HR Manager (2nd level),
                                                then Principal (final)
        state 'validate'  (Approved)         -> approved

    Inside 'validate1', school_hr_approved tells whether the HR Manager has
    already approved (i.e. waiting for the Principal).

    Rules:
      * Non-medical leave must be requested >= 3 days before it starts.
      * Leave of 30+ calendar days must be requested >= 10 days before.
      * Principal must approve >= 1 day before the leave starts (non-medical).
      * Medical leave needs a medical certificate (attachment) for any duration.

    Notifications (inbox for internal users, email for portal users):
      * Teacher applies        -> Admin + HR: inbox message + sticky pop-up + dashboard
                                  refresh; teacher: "submitted" e-mail
      * Admin approves         -> HR Managers: "waiting for you"; teacher: progress
      * HR Manager approves    -> Principals: "waiting for you"; teacher: progress
      * Principal approves     -> teacher: "approved"
      * Refused (any level)    -> teacher: "refused by <level>"
    """
    _inherit = 'hr.leave'

    is_school_workflow = fields.Boolean(
        related='holiday_status_id.school_approval_workflow', string='School Approval Workflow')
    school_is_medical = fields.Boolean(
        related='holiday_status_id.school_is_medical', string='Medical Leave')

    school_approval_stage = fields.Selection(
        [
            ('admin', 'Admin Approval'),
            ('hr', 'HR Manager Approval'),
            ('principal', 'Principal Approval'),
            ('approved', 'Approved'),
            ('refused', 'Refused'),
            ('cancelled', 'Cancelled'),
        ],
        string='Approval Stage', compute='_compute_school_approval_stage',
        store=True, tracking=True,
    )
    school_hr_approved = fields.Boolean(string='HR Manager Approved', copy=False, readonly=True)

    school_admin_approver_id = fields.Many2one('res.users', string='Admin Approved By', copy=False, readonly=True)
    school_admin_approval_date = fields.Datetime(string='Admin Approval Date', copy=False, readonly=True)
    school_hr_approver_id = fields.Many2one('res.users', string='HR Manager Approved By', copy=False, readonly=True)
    school_hr_approval_date = fields.Datetime(string='HR Approval Date', copy=False, readonly=True)
    school_principal_approver_id = fields.Many2one('res.users', string='Principal Approved By', copy=False, readonly=True)
    school_principal_approval_date = fields.Datetime(string='Principal Approval Date', copy=False, readonly=True)

    school_notice_given_days = fields.Integer(
        string='Prior Notice (days)', compute='_compute_school_notice_info',
        help='Days between the request date and the first day of leave.')
    school_principal_deadline = fields.Date(
        string='Principal Must Approve By', compute='_compute_school_notice_info')
    school_notice_warning = fields.Char(compute='_compute_school_notice_info')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('state', 'school_hr_approved', 'holiday_status_id.school_approval_workflow')
    def _compute_school_approval_stage(self):
        for leave in self:
            if not leave.holiday_status_id.school_approval_workflow:
                leave.school_approval_stage = False
            elif leave.state == 'confirm':
                leave.school_approval_stage = 'admin'
            elif leave.state == 'validate1':
                leave.school_approval_stage = 'principal' if leave.school_hr_approved else 'hr'
            elif leave.state == 'validate':
                leave.school_approval_stage = 'approved'
            elif leave.state == 'refuse':
                leave.school_approval_stage = 'refused'
            else:
                leave.school_approval_stage = 'cancelled'

    @api.depends('request_date_from', 'request_date_to', 'holiday_status_id', 'state', 'create_date')
    def _compute_school_notice_info(self):
        today = fields.Date.context_today(self)
        for leave in self:
            start = leave._school_start_date()
            ref_date = leave.create_date.date() if leave.create_date else today
            leave.school_notice_given_days = (start - ref_date).days if start else 0
            lead = leave.holiday_status_id.school_principal_lead_days
            leave.school_principal_deadline = (
                fields.Date.subtract(start, days=lead)
                if start and leave.is_school_workflow and not leave.school_is_medical else False
            )
            leave.school_notice_warning = (
                leave._school_get_notice_error(ref_date)
                if leave.state == 'confirm' else False
            )

    @api.depends('school_hr_approved')
    def _compute_can_approve(self):
        super()._compute_can_approve()
        for leave in self:
            if leave.is_school_workflow and leave.state == 'validate1' and not leave.school_hr_approved:
                # HR Manager step: no state change, so it isn't covered by the
                # standard state-transition check.
                leave.can_approve = leave._school_user_can('hr')

    @api.depends('school_hr_approved')
    def _compute_can_validate(self):
        super()._compute_can_validate()

    @api.depends('school_hr_approved')
    def _compute_can_refuse(self):
        super()._compute_can_refuse()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _school_start_date(self):
        self.ensure_one()
        return self.request_date_from or (self.date_from and self.date_from.date())

    def _school_end_date(self):
        self.ensure_one()
        return self.request_date_to or (self.date_to and self.date_to.date()) or self._school_start_date()

    def _school_user_can(self, level):
        return self.env.is_superuser() or self.env.user.has_group(SCHOOL_LEVEL_GROUPS[level])

    def _school_has_certificate(self):
        self.ensure_one()
        return bool(self.env['ir.attachment'].sudo().search_count([
            ('res_model', '=', 'hr.leave'), ('res_id', '=', self.id),
        ]))

    def _school_get_notice_error(self, ref_date=None):
        """Return an error message if the prior-notice rules are broken."""
        self.ensure_one()
        if not self.is_school_workflow or self.school_is_medical:
            return False
        start = self._school_start_date()
        if not start:
            return False
        ref_date = ref_date or fields.Date.context_today(self)
        leave_type = self.holiday_status_id
        notice = (start - ref_date).days
        duration = (self._school_end_date() - start).days + 1

        if (leave_type.school_long_leave_days and duration >= leave_type.school_long_leave_days
                and notice < leave_type.school_long_leave_notice_days):
            return _(
                "Leave of %(limit)s days or more (requested: %(duration)s days) must be applied "
                "at least %(notice)s days before it starts. You are applying %(given)s day(s) before.",
                limit=leave_type.school_long_leave_days, duration=duration,
                notice=leave_type.school_long_leave_notice_days, given=max(notice, 0),
            )
        if notice < leave_type.school_notice_days:
            return _(
                "%(type)s must be pre-informed at least %(notice)s days before the leave starts "
                "(medical leave is exempt). You are applying %(given)s day(s) before.",
                type=leave_type.name, notice=leave_type.school_notice_days, given=max(notice, 0),
            )
        return False

    def _school_check_notice(self):
        for leave in self:
            message = leave._school_get_notice_error()
            if message:
                raise ValidationError(message)

    def _school_check_before_approval(self):
        """Rights, medical certificate and Principal deadline for the pending level."""
        for leave in self:
            level = {'admin': 'admin', 'hr': 'hr', 'principal': 'principal'}.get(leave.school_approval_stage)
            if not level:
                raise UserError(_("Time off %s is not waiting for approval.", leave.display_name))
            if not leave._school_user_can(level):
                raise UserError(_(
                    "This request is waiting for %(level)s approval. You are not allowed to approve it.",
                    level=SCHOOL_LEVEL_LABELS[level],
                ))
            if leave.school_is_medical and not leave._school_has_certificate():
                raise UserError(_(
                    "A medical certificate is required for medical leave (any duration). "
                    "Please attach it before approving."
                ))
            if level == 'principal' and not leave.school_is_medical:
                start = leave._school_start_date()
                lead = leave.holiday_status_id.school_principal_lead_days
                today = fields.Date.context_today(leave)
                if start and (start - today).days < lead:
                    raise UserError(_(
                        "Principal approval must be given at least %(lead)s day(s) before the leave "
                        "starts (%(start)s). The deadline has passed, so this request should be refused "
                        "and re-applied.",
                        lead=lead, start=start,
                    ))

    # ------------------------------------------------------------------
    # Standard workflow hooks
    # ------------------------------------------------------------------
    def _get_next_states_by_state(self):
        """Restrict the standard state transitions to the school levels."""
        result = super()._get_next_states_by_state()
        if not self.is_school_workflow:
            return result

        approval_states = {'validate1', 'validate', 'refuse'}
        result['confirm'] -= approval_states
        result['validate1'] -= approval_states
        # A refused/cancelled request goes back through the full flow (via 'confirm').
        result['refuse'] -= {'validate1', 'validate'}
        result['cancel'] -= {'validate1', 'validate'}
        # Once approved by the Principal, the approval is final: no "Back to
        # Approval" (Approved -> To Approve). Refuse / Cancel stay available.
        # System processes (e.g. contract changes) run as superuser and are
        # not affected by this rule.
        result['validate'].discard('confirm')

        if self._school_user_can('admin'):
            result['confirm'] |= {'validate1', 'refuse'}
        if not self.school_hr_approved:
            if self._school_user_can('hr'):
                result['validate1'].add('refuse')
        elif self._school_user_can('principal'):
            result['validate1'] |= {'validate', 'refuse'}
        return result

    def _get_responsible_for_approval(self):
        """Activities go to the users of the pending school level."""
        self.ensure_one()
        if not self.is_school_workflow:
            return super()._get_responsible_for_approval()
        level = {'admin': 'admin', 'hr': 'hr', 'principal': 'principal'}.get(self.school_approval_stage)
        return self._school_level_users(level) if level else self.env['res.users']

    def _school_level_users(self, level):
        """Active internal users of a school approval level, in the employee's company."""
        self.ensure_one()
        group = self.env.ref(SCHOOL_LEVEL_GROUPS[level], raise_if_not_found=False)
        if not group:
            return self.env['res.users']
        company = self.employee_id.company_id or self.env.company
        return group.sudo().all_user_ids.filtered(
            lambda u: u.active and not u.share and company in u.company_ids
        )

    def action_approve(self, check_state=True):
        school_leaves = self.filtered('is_school_workflow')
        school_leaves._school_check_before_approval()

        admin_stage = school_leaves.filtered(lambda l: l.state == 'confirm')
        hr_stage = school_leaves.filtered(lambda l: l.state == 'validate1' and not l.school_hr_approved)
        principal_stage = school_leaves.filtered(lambda l: l.state == 'validate1' and l.school_hr_approved)
        now = fields.Datetime.now()

        if admin_stage:
            admin_stage.sudo().write({'school_admin_approver_id': self.env.uid, 'school_admin_approval_date': now})
        if principal_stage:
            principal_stage.sudo().write({'school_principal_approver_id': self.env.uid,
                                          'school_principal_approval_date': now})
        if hr_stage:
            hr_stage._school_action_hr_approve()

        # Admin (confirm -> validate1) and Principal (validate1 -> validate)
        # use the standard approval, so balances, calendar and resource
        # leaves are handled by Odoo exactly as usual.
        standard = self - hr_stage
        if standard:
            # school_leave_mute_core: the core "has been accepted" post is replaced
            # by _school_notify_approved() (see message_post below).
            super(HrLeave, standard.with_context(school_leave_mute_core=True)).action_approve(
                check_state=check_state)

        for leave in admin_stage:
            leave.message_post(body=_("1st level approval by Administration (%s). Waiting for HR Manager approval.",
                                      self.env.user.name))
        admin_stage._school_notify_progress('admin')
        principal_stage._school_notify_approved()
        return True

    def _school_action_hr_approve(self):
        self.sudo().activity_feedback(['hr_holidays.mail_act_leave_second_approval'])
        self.sudo().write({
            'school_hr_approved': True,
            'school_hr_approver_id': self.env.uid,
            'school_hr_approval_date': fields.Datetime.now(),
        })
        self.invalidate_recordset(['can_approve', 'can_validate', 'can_refuse', 'school_approval_stage'])
        # Standard activity update: state is still 'validate1', and the
        # responsible users are now the Principals.
        self.activity_update()
        for leave in self:
            leave.message_post(body=_("2nd level approval by HR Manager (%s). Waiting for Principal approval.",
                                      self.env.user.name))
        self._school_notify_progress('hr')

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def _school_skip_notice_check(self):
        ctx = self.env.context
        return (ctx.get('leave_fast_create') or ctx.get('import_file')
                or ctx.get('leave_skip_state_check') or ctx.get('school_leave_skip_notice'))

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)
        if not self._school_skip_notice_check():
            leaves.filtered(lambda l: l.is_school_workflow and l.state == 'confirm')._school_check_notice()
        if not self._school_skip_notification():
            # Teacher applied: tell the Admin approvers and confirm to the teacher.
            leaves.filtered(lambda l: l.is_school_workflow and l.state == 'confirm')._school_notify_submitted()
        return leaves

    def write(self, vals):
        resubmitted = self.env['hr.leave']
        if vals.get('state') == 'confirm':
            # Refused / cancelled / approved request sent back to "To Approve":
            # the approvers must hear about it again.
            resubmitted = self.filtered(lambda l: l.is_school_workflow and l.state != 'confirm')
            # Reset to "To Approve": the whole approval chain starts again.
            vals = dict(vals, school_hr_approved=False,
                        school_admin_approver_id=False, school_admin_approval_date=False,
                        school_hr_approver_id=False, school_hr_approval_date=False,
                        school_principal_approver_id=False, school_principal_approval_date=False)
        result = super().write(vals)
        if {'request_date_from', 'request_date_to', 'holiday_status_id'} & set(vals) \
                and not self._school_skip_notice_check():
            self.filtered(lambda l: l.is_school_workflow and l.state == 'confirm')._school_check_notice()
        if resubmitted and not self._school_skip_notification():
            resubmitted.filtered(lambda l: l.state == 'confirm')._school_notify_submitted(resubmitted=True)
        return result

    # ------------------------------------------------------------------
    # Activities: keep the To-Do, drop Odoo's generic "assigned" e-mail
    # (the school notifications below replace it, so approvers don't get
    # two messages for the same request).
    # ------------------------------------------------------------------
    def activity_update(self):
        school_leaves = self.filtered('is_school_workflow')
        if school_leaves:
            super(HrLeave, school_leaves.with_context(mail_activity_quick_update=True)).activity_update()
        other_leaves = self - school_leaves
        if other_leaves:
            super(HrLeave, other_leaves).activity_update()

    def action_refuse(self):
        school_leaves = self.filtered('is_school_workflow')
        stage_before = {leave.id: leave.school_approval_stage for leave in school_leaves}
        result = super(HrLeave, self.with_context(school_leave_mute_core=True)).action_refuse()
        school_leaves._school_notify_refused(stage_before)
        return result

    def message_post(self, **kwargs):
        """Core hr_holidays posts "accepted"/"refused" as an INTERNAL note addressed
        to the employee: a portal teacher receives it as "Internal communication"
        with a raw UTC date. For school leaves the post stays in the chatter but
        nobody is pinged; the school notifications send a clear message instead."""
        if (self.env.context.get('school_leave_mute_core') and kwargs.get('partner_ids')
                and len(self) == 1 and self.is_school_workflow):
            kwargs = dict(kwargs, partner_ids=[])
        return super().message_post(**kwargs)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _school_skip_notification(self):
        ctx = self.env.context
        return (ctx.get('leave_fast_create') or ctx.get('import_file')
                or ctx.get('mail_notify_off') or ctx.get('school_leave_no_notify'))

    def _school_teacher_partner(self):
        self.ensure_one()
        return self.employee_id.user_id.partner_id or self.employee_id.work_contact_id

    def _school_pending_approver_partners(self):
        """Partners of the users who must approve the CURRENT level."""
        self.ensure_one()
        users = self.sudo()._get_responsible_for_approval()
        # The person who just acted (or the applicant) doesn't need a notice.
        return (users - self.env.user - self.employee_id.user_id).partner_id

    def _school_render_notification(self, partner, message, for_teacher=False):
        self.ensure_one()
        start, end = self._school_start_date(), self._school_end_date()
        stage_labels = dict(self._fields['school_approval_stage']._description_selection(self.env))
        if self.leave_type_request_unit == 'hour':
            duration = _("%s hour(s)", round(self.number_of_hours, 2))
        else:
            duration = _("%s day(s)", round(self.number_of_days, 2))
        values = {
            'recipient_name': partner.name or '',
            'message': message,
            'employee_name': self.employee_id.name or '',
            'leave_type': self.holiday_status_id.name or '',
            'date_from': format_date(self.env, start) if start else '',
            'date_to': format_date(self.env, end) if end else '',
            'duration': duration,
            'reason': self.sudo().private_name or '',
            'status': stage_labels.get(self.school_approval_stage, self.school_approval_stage or ''),
            'deadline': (format_date(self.env, self.school_principal_deadline)
                         if self.school_principal_deadline and self.state in ('confirm', 'validate1') else ''),
            'portal_url': (self.get_base_url() + '/my/leaves') if for_teacher else '',
        }
        return self.env['ir.qweb']._render(
            'ad_school_management.school_leave_notification_body', values, minimal_qcontext=True)

    def _school_send_notification(self, partners, subject, message, for_teacher=False):
        """Inbox notification for internal users, e-mail for portal users / no-login staff.

        Approvers get the standard layout with a "View Time Off" button; the
        teacher gets the light layout and a link to the portal page (a portal
        user cannot open the back-end form).
        """
        self.ensure_one()
        layout = 'mail.mail_notification_light' if for_teacher else 'mail.mail_notification_layout'
        for partner in partners:
            self.sudo().message_notify(
                partner_ids=partner.ids,
                subject=subject,
                body=self._school_render_notification(partner, message, for_teacher=for_teacher),
                model_description=_('Leave Request'),
                email_layout_xmlid=layout,
            )

    def _school_warn_no_approver(self, level):
        self.ensure_one()
        self.message_post(body=_(
            "No user found in the %(level)s group, so nobody was notified about this request. "
            "Add users to that group (Settings > Users) to receive leave notifications.",
            level=SCHOOL_LEVEL_LABELS[level],
        ))

    def _school_notify_submitted(self, resubmitted=False):
        """Employee applied for leave.

        * Admin (1st level): inbox message "waiting for your approval".
        * HR Manager: inbox message "for your information" (they approve next).
        * Admin + HR: real-time sticky pop-up on their Odoo screen and a live
          refresh of the School Dashboard (same mechanism as the birthday
          notification).
        * Employee: confirmation e-mail.
        """
        for leave in self:
            employee = leave.employee_id.name
            leave_type = leave.holiday_status_id.name
            applicant = leave.employee_id.user_id
            admin_users = leave._school_level_users('admin') - applicant
            hr_users = leave._school_level_users('hr') - applicant - admin_users

            if admin_users:
                leave._school_send_notification(
                    admin_users.partner_id,
                    subject=_("New Leave Request: %(employee)s (%(type)s)", employee=employee, type=leave_type),
                    message=(_("%(employee)s has re-submitted a leave request. It is waiting for your "
                               "approval (1st level – Administration).", employee=employee)
                             if resubmitted else
                             _("%(employee)s has applied for leave. It is waiting for your approval "
                               "(1st level – Administration).", employee=employee)),
                )
            else:
                leave._school_warn_no_approver('admin')

            if hr_users:
                leave._school_send_notification(
                    hr_users.partner_id,
                    subject=_("New Leave Request: %(employee)s (%(type)s)", employee=employee, type=leave_type),
                    message=_("%(employee)s has applied for leave. It is now with Administration "
                              "(1st level); you will be asked to approve it next (2nd level – HR Manager).",
                              employee=employee),
                )

            leave._school_push_dashboard_alert(admin_users | hr_users, resubmitted=resubmitted)

            teacher = leave._school_teacher_partner()
            if teacher:
                leave._school_send_notification(
                    teacher,
                    subject=_("Leave Request Submitted: %s", leave_type),
                    message=_("Your leave request has been submitted successfully. It is now waiting "
                              "for Administration approval. You will be notified at every step."),
                    for_teacher=True,
                )

    def _school_push_dashboard_alert(self, users, resubmitted=False):
        """Real-time pop-up for Admin/HR (like the birthday notification) and a
        signal that makes an open School Dashboard reload its leave panel.

        The bus message is sent when the transaction commits, so it only
        appears if the leave request was really saved."""
        self.ensure_one()
        if not users:
            return
        start, end = self._school_start_date(), self._school_end_date()
        dates = format_date(self.env, start) if start else ''
        if end and end != start:
            dates = "%s → %s" % (dates, format_date(self.env, end))
        if self.leave_type_request_unit == 'hour':
            duration = _("%s hour(s)", round(self.number_of_hours, 2))
        else:
            duration = _("%s day(s)", round(self.number_of_days, 2))
        title = (_("Leave Request Re-submitted") if resubmitted else _("New Leave Request"))
        message = _(
            "%(employee)s applied for %(type)s · %(dates)s (%(duration)s) · Reason: %(reason)s",
            employee=self.employee_id.name, type=self.holiday_status_id.name,
            dates=dates, duration=duration, reason=self.sudo().private_name or '-',
        )
        Bus = self.env['bus.bus'].sudo()
        for partner in users.partner_id:
            Bus._sendone(partner, 'simple_notification', {
                'type': 'warning',
                'title': title,
                'message': message,
                'sticky': True,
            })
            Bus._sendone(partner, 'school_leave_request', {'leave_id': self.id})

    def _school_notify_progress(self, approved_level):
        """A level approved: notify the next level and keep the teacher informed."""
        next_level = {'admin': 'hr', 'hr': 'principal'}[approved_level]
        approved_label = {'admin': _('Administration'), 'hr': _('HR Manager')}[approved_level]
        next_label = {'hr': _('HR Manager'), 'principal': _('Principal')}[next_level]
        step = {'hr': _('2nd level – HR Manager'), 'principal': _('final level – Principal')}[next_level]
        for leave in self:
            employee = leave.employee_id.name
            approvers = leave._school_pending_approver_partners()
            if approvers:
                leave._school_send_notification(
                    approvers,
                    subject=_("Leave Approval Needed: %(employee)s (%(type)s)",
                              employee=employee, type=leave.holiday_status_id.name),
                    message=_("The leave request of %(employee)s was approved by %(by)s (%(user)s) and is "
                              "now waiting for your approval (%(step)s).",
                              employee=employee, by=approved_label, user=self.env.user.name, step=step),
                )
            else:
                leave._school_warn_no_approver(next_level)

            teacher = leave._school_teacher_partner()
            if teacher:
                leave._school_send_notification(
                    teacher,
                    subject=_("Leave Request Update: approved by %s", approved_label),
                    message=_("Good news: your leave request was approved by %(by)s. "
                              "It is now waiting for %(next)s approval.",
                              by=approved_label, next=next_label),
                    for_teacher=True,
                )

    def _school_notify_approved(self):
        """Principal gave the final approval: tell the teacher."""
        for leave in self:
            leave.message_post(body=_("Final approval by Principal (%s). Leave approved.", self.env.user.name))
            teacher = leave._school_teacher_partner()
            if teacher:
                leave._school_send_notification(
                    teacher,
                    subject=_("Leave Approved: %s", leave.holiday_status_id.name),
                    message=_("Your leave request has been fully approved by the Principal. Enjoy your leave!"),
                    for_teacher=True,
                )

    def _school_notify_refused(self, stage_before):
        """Request refused at any level: tell the teacher who refused it."""
        level_labels = {'admin': _('Administration'), 'hr': _('the HR Manager'),
                        'principal': _('the Principal'), 'approved': _('the school')}
        for leave in self:
            by = level_labels.get(stage_before.get(leave.id), _('the school'))
            leave.message_post(body=_("Refused by %(by)s (%(user)s).", by=by, user=self.env.user.name))
            teacher = leave._school_teacher_partner()
            if teacher:
                leave._school_send_notification(
                    teacher,
                    subject=_("Leave Refused: %s", leave.holiday_status_id.name),
                    message=_("Sorry, your leave request was refused by %(by)s (%(user)s). "
                              "If you still need this leave, please contact the office or apply again.",
                              by=by, user=self.env.user.name),
                    for_teacher=True,
                )
