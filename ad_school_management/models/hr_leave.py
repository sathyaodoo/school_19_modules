from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

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
        group = level and self.env.ref(SCHOOL_LEVEL_GROUPS[level], raise_if_not_found=False)
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
            super(HrLeave, standard).action_approve(check_state=check_state)

        for leave in admin_stage:
            leave.message_post(body=_("1st level approval by Administration (%s). Waiting for HR Manager approval.",
                                      self.env.user.name))
        for leave in principal_stage:
            leave.message_post(body=_("Final approval by Principal (%s). Leave approved.", self.env.user.name))
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
        return leaves

    def write(self, vals):
        if vals.get('state') == 'confirm':
            # Reset to "To Approve": the whole approval chain starts again.
            vals = dict(vals, school_hr_approved=False,
                        school_admin_approver_id=False, school_admin_approval_date=False,
                        school_hr_approver_id=False, school_hr_approval_date=False,
                        school_principal_approver_id=False, school_principal_approval_date=False)
        result = super().write(vals)
        if {'request_date_from', 'request_date_to', 'holiday_status_id'} & set(vals) \
                and not self._school_skip_notice_check():
            self.filtered(lambda l: l.is_school_workflow and l.state == 'confirm')._school_check_notice()
        return result